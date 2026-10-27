"""Generic local-only OCR and table parsing for GRN invoice suggestions."""
import io, os, re, uuid, datetime as dt
from collections import defaultdict
from difflib import SequenceMatcher
import fitz
import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from pytesseract import Output
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app import models
from app.database import get_db

router = APIRouter(tags=["GRN document extraction"])
MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 12
META = {
 "invoice_no": ("invoice no", "invoice number", "tax invoice no", "bill no", "inv no"),
 "invoice_date": ("invoice date", "bill date", "date of invoice", "dated"),
 "po_no": ("purchase order no", "purchase order number", "po no", "po number"),
 "gstin": ("gstin", "gst registration no", "gst no"),
}
ALIASES = {
 "item_name": ("description of goods", "item description", "material description", "particulars", "product name", "item name", "description", "details"),
 "qty": ("quantity", "qty", "billed qty", "bill qty"),
 "unit": ("unit", "uom", "units"),
 "gst": ("gst %", "gst rate", "tax %", "igst", "cgst", "sgst", "gst"),
 "rate": ("unit price", "price per unit", "unit rate", "rate"),
 "amount": ("line amount", "net amount", "taxable value", "total amount", "amount", "amt", "value"),
}
NUM = re.compile(r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?")
DATE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
def norm(s): return re.sub(r"[^a-z0-9%]+", " ", (s or "").lower()).strip()

def ocr_image(image, page):
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageEnhance.Contrast(ImageOps.autocontrast(ImageOps.grayscale(image))).enhance(1.5).filter(ImageFilter.SHARPEN)
    cmd = os.getenv("TESSERACT_CMD")
    if cmd and os.path.exists(cmd): pytesseract.pytesseract.tesseract_cmd = cmd
    words = []
    try:
        d = pytesseract.image_to_data(image, config="--oem 3 --psm 6", output_type=Output.DICT)
        for i, raw in enumerate(d["text"]):
            text = raw.strip()
            try: conf = float(d["conf"][i])
            except (ValueError, TypeError): conf = -1
            if text and conf >= 0:
                words.append(dict(text=text,x0=d["left"][i],x1=d["left"][i]+d["width"][i],top=d["top"][i],bottom=d["top"][i]+d["height"][i],page=page,confidence=conf/100))
    except Exception: pass
    if len(words) >= 8: return words
    # PaddleOCR is an offline fallback and is loaded only when installed/needed.
    try:
        from paddleocr import PaddleOCR
        import numpy as np
        global _paddle
        if "_paddle" not in globals(): _paddle = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        for block in (_paddle.ocr(np.array(image.convert("RGB")), cls=True) or []):
            for box, pair in block or []:
                xs=[p[0] for p in box]; ys=[p[1] for p in box]
                words.append(dict(text=str(pair[0]),x0=min(xs),x1=max(xs),top=min(ys),bottom=max(ys),page=page,confidence=float(pair[1])))
    except Exception: pass
    return words

def get_words(data, ext):
    words=[]
    if ext == ".pdf":
        with fitz.open(stream=data,filetype="pdf") as doc:
            if len(doc)>MAX_PAGES: raise HTTPException(413, f"PDF must contain {MAX_PAGES} pages or fewer.")
            for pi,page in enumerate(doc,1):
                embedded=page.get_text("words")
                if len(embedded)>=12:
                    words.extend(dict(text=str(w[4]),x0=w[0],x1=w[2],top=w[1],bottom=w[3],page=pi,confidence=1) for w in embedded)
                else:
                    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                    words.extend(ocr_image(Image.open(io.BytesIO(pix.tobytes("png"))),pi))
    else:
        try: words=ocr_image(Image.open(io.BytesIO(data)),1)
        except Exception: raise HTTPException(400,"The image file could not be read.")
    return words

def make_rows(words):
    groups=defaultdict(list)
    for w in words: groups[w["page"],round(float(w["top"])/5)].append(w)
    rows=[]
    for key,row in sorted(groups.items()):
        row.sort(key=lambda w:w["x0"])
        if rows and rows[-1][0]["page"]==key[0] and abs(sum(w["top"] for w in rows[-1])/len(rows[-1])-sum(w["top"] for w in row)/len(row))<8:
            rows[-1].extend(row); rows[-1].sort(key=lambda w:w["x0"])
        else: rows.append(row)
    return rows

def parse_lines(rows):
    aliases={k:[norm(x) for x in v] for k,v in ALIASES.items()}
    header=None; cols=[]
    for ri,row in enumerate(rows):
        found={}
        for w in row:
            n=norm(w["text"])
            for field, names in aliases.items():
                if n in names or any(n.startswith(a+" ") for a in names):
                    found.setdefault(field,(float(w["x0"])+float(w["x1"]))/2)
        if "item_name" in found and len(found)>=3:
            header=ri; cols=sorted(found.items(),key=lambda x:x[1]); break
    if header is None: return []
    bounds=[]
    for i,(field,x) in enumerate(cols):
        bounds.append((field, -1e9 if i==0 else (cols[i-1][1]+x)/2, 1e9 if i==len(cols)-1 else (x+cols[i+1][1])/2))
    result=[]
    for row in rows[header+1:]:
        full=" ".join(w["text"] for w in row)
        # Stop at invoice summaries, amount-in-words, banking details and footer/terms.
        if re.search(r"\\b(sub\\s*total|grand\\s*total|invoice\\s*total|amount\\s*payable|round\\s*off|amount\\s*in\\s*words|bank|terms\\s*(?:&|and)?\\s*conditions|authori[sz]ed\\s*signatory|total\\s*(?:tax|gst|amount))\\b",full,re.I):
            break
        cells={f:" ".join(w["text"] for w in row if left <= (float(w["x0"])+float(w["x1"]))/2 < right).strip() for f,left,right in bounds}
        name=cells.get("item_name","").strip(" -:.")
        # Strip the invoice's serial number from the description field.
        name=re.sub(r"^\\s*\\d{1,3}\\s*[.)-]?\\s+", "", name)
        if not name: continue
        if re.search(r"\\b(rs|rupees|only|hundred|thousand|lakh|lakhs|crore|bank|account|ifsc|branch)\\b",name,re.I):
            break
        vals={}
        for f in ("qty","rate","amount"):
            m=NUM.search(cells.get(f,""))
            vals[f]=float(m.group(0).replace(",","")) if m else None
        if not vals["qty"] or vals["qty"]<=0:
            # Preserve wrapped descriptions rather than treating them as separate items.
            if result and len(name)>1 and not NUM.search(full): result[-1]["item_name"] += " "+name
            continue
        result.append(dict(item_name=name,qty=vals["qty"],unit=cells.get("unit",""),gst=cells.get("gst",""),rate=vals["rate"],amount=vals["amount"],confidence=round(sum(w.get("confidence",.8) for w in row)/len(row),3)))
    return result

def metadata(text):
    out={k:"" for k in META}
    for line in text.splitlines():
        line=re.sub(r"\s+"," ",line).strip()
        for field,aliases in META.items():
            if out[field]: continue
            for alias in aliases:
                m=re.search(re.escape(alias)+r"\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/_.\-]{2,})",line,re.I)
                if m: out[field]=m.group(1).strip(" :#-"); break
        if not out["invoice_date"] and re.search(r"invoice|bill|dated|date",line,re.I):
            m=DATE.search(line)
            if m: out["invoice_date"]=m.group(0)
        if not out["gstin"]:
            m=re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b",line,re.I)
            if m: out["gstin"]=m.group(0)
    return out

def match_item(name, items):
    n=norm(name); scored=sorted(((1 if n==norm(i.name or "") else SequenceMatcher(None,n,norm(i.name or "")).ratio(),i) for i in items if i.name),key=lambda x:x[0],reverse=True)
    if scored and scored[0][0]>=.78: return scored[0][1].code,scored[0][1].name,round(scored[0][0],3)
    return "", "", round(scored[0][0],3) if scored else 0

def cleanup(db):
    cutoff=(dt.datetime.utcnow()-dt.timedelta(hours=24)).isoformat()
    ids=[s.id for s in db.query(models.GRNExtractionSessionModel).filter(models.GRNExtractionSessionModel.created_at<cutoff).all()]
    if ids:
        db.query(models.GRNExtractionLineModel).filter(models.GRNExtractionLineModel.extraction_id.in_(ids)).delete(synchronize_session=False)
        db.query(models.GRNExtractionSessionModel).filter(models.GRNExtractionSessionModel.id.in_(ids)).delete(synchronize_session=False); db.commit()

@router.post("/grns/extract-document")
async def extract_document(file: UploadFile=File(...), db: Session=Depends(get_db)):
    filename=file.filename or "receipt"; ext=os.path.splitext(filename.lower())[1]
    if ext not in {".pdf",".jpg",".jpeg",".png"}: raise HTTPException(415,"Upload a PDF, JPG, JPEG, or PNG file.")
    data=await file.read()
    if not data or len(data)>MAX_BYTES: raise HTTPException(413 if data else 400,"File is empty or exceeds the 15 MB limit.")
    cleanup(db); words=get_words(data,ext); rows=make_rows(words)
    text="\n".join(" ".join(w["text"] for w in row) for row in rows)
    meta=metadata(text); lines=parse_lines(rows)
    items=db.query(models.ItemModel).filter(models.ItemModel.status=="Active").all()
    vendors=db.query(models.VendorModel).filter(models.VendorModel.status=="Active").all()
    for line in lines:
        line["item_code"],line["matched_item_name"],line["match_confidence"]=match_item(line["item_name"],items)
    # Vendor matching is conservative; GSTIN match takes precedence.
    gst=meta["gstin"].upper(); vendor_match=None
    for v in vendors:
        if gst and (v.gst_no or "").upper()==gst: vendor_match=v; break
    if not vendor_match:
        normtext=norm(text)
        scores=[(SequenceMatcher(None,normtext[:120],norm(v.name or "")).ratio(),v) for v in vendors if v.name]
        scores.sort(key=lambda x:x[0],reverse=True)
        if scores and scores[0][0]>=.72: vendor_match=scores[0][1]
    vendor={"vendor_code":vendor_match.code if vendor_match else "", "vendor_name":vendor_match.name if vendor_match else ""}
    eid=uuid.uuid4().hex; now=dt.datetime.utcnow().isoformat()
    db.add(models.GRNExtractionSessionModel(id=eid,filename=filename,created_at=now,invoice_no=meta["invoice_no"],invoice_date=meta["invoice_date"],po_no=meta["po_no"],gstin=meta["gstin"],vendor_code=vendor["vendor_code"],vendor_name=vendor["vendor_name"],raw_text=text[:50000],status="pending"))
    for i,line in enumerate(lines):
        db.add(models.GRNExtractionLineModel(id=f"{eid}:{i}",extraction_id=eid,line_no=i+1,item_name=line["item_name"],item_code=line["item_code"],qty=line["qty"],unit=line["unit"],gst=line["gst"],rate=line["rate"],amount=line["amount"],confidence=line["confidence"]))
    db.commit()
    return {"extraction_id":eid,"filename":filename,"metadata":meta,"vendor":vendor,"line_items":lines,"line_count":len(lines),"warnings":[] if lines else ["Could not confidently detect an item table. No quantities or rates were guessed; review manually."],"ocr_words":len(words),"text_preview":text[:2500]}

@router.delete("/grns/extractions/{extraction_id}")
def discard_extraction(extraction_id:str,db:Session=Depends(get_db)):
    db.query(models.GRNExtractionLineModel).filter_by(extraction_id=extraction_id).delete(synchronize_session=False)
    db.query(models.GRNExtractionSessionModel).filter_by(id=extraction_id).delete(synchronize_session=False)
    db.commit()
    return {"deleted":True}

"""Shared keyword-driven GRN header extraction for PDF text and OCR text."""
import re
from datetime import datetime
from difflib import SequenceMatcher
from app import models

# Central alias registry: extend aliases here instead of adding supplier-specific branches.
KEYWORDS = {
 "invoice_no": [r"(?:tax\s*)?invoice\s*(?:no\.?|number|#)", r"\binv\.?\s*(?:no\.?|number|#)", r"\bbill\s*(?:no\.?|number|#)"],
 "po_no": [r"purchase\s*order\s*(?:no\.?|number|ref(?:erence)?|#)", r"\bP\.?\s*O\.?\s*(?:no\.?|number|#)"],
 "date": [r"invoice\s*date", r"bill\s*date", r"date\s*of\s*invoice", r"\bdated\b", r"\bdate\b"],
 "vendor": [r"supplier\s*(?:name)?", r"vendor\s*(?:name)?", r"seller\s*(?:name)?"],
}
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = rf"(?:\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|\d{{1,2}}[ ./-](?:{MONTHS})[ ./,-]+\d{{2,4}}|\d{{4}}[./-]\d{{1,2}}[./-]\d{{1,2}})"
DATE_FORMATS = ("%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%d/%m/%y","%d-%m-%y","%d.%m.%y","%d-%b-%Y","%d-%b-%y","%d %b %Y","%d %b %y","%d-%B-%Y","%d-%B-%y","%d %B %Y","%d %B %y","%Y-%m-%d","%Y/%m/%d","%Y.%m.%d")

def _norm(s):
 return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def _capture(text, aliases, value_pattern):
 for alias in aliases:
  m = re.search(rf"(?:{alias})\s*[:#=-]?\s*({value_pattern})", text, re.I|re.M)
  if not m:
   m = re.search(rf"(?:{alias})[^\n]{{0,20}}\n\s*({value_pattern})", text, re.I|re.M)
  if m:
   value = re.sub(r"\s+", " ", m.group(1)).strip(" :#-;|\t")
   if value: return value
 return None

def _date(text):
 normalized = text.replace("–","-").replace("—","-").replace("−","-")
 normalized = re.sub(r"(?<=\d)\s*-\s*(?=[A-Za-z])","-",normalized)
 normalized = re.sub(r"(?<=[A-Za-z])\s*-\s*(?=\d)","-",normalized)
 candidates=[]
 for alias in KEYWORDS["date"]:
  candidates += re.findall(rf"(?:{alias})\s*[:#=-]?\s*({DATE_RE})",normalized,re.I)
  candidates += re.findall(rf"(?:{alias})[^\n]{{0,20}}\n\s*({DATE_RE})",normalized,re.I)
 if not candidates: candidates=re.findall(DATE_RE,normalized,re.I)
 for raw in candidates:
  raw=re.sub(r"(?i)(\d)(st|nd|rd|th)\b",r"\1",raw.strip())
  raw=re.sub(r"\s+"," ",raw.replace(","," ")).strip()
  for fmt in DATE_FORMATS:
   try:
    d=datetime.strptime(raw,fmt).date()
    if 1990 <= d.year <= datetime.now().year+2: return d.isoformat()
   except ValueError: pass
 return None

def extract_header_fields(text, db):
 text=text or ""
 # Restrict IDs to a single plausible token; don't consume following labels.
 id_pattern=r"[A-Z0-9][A-Z0-9/_.-]{2,40}"
 invoice=_capture(text,KEYWORDS["invoice_no"],id_pattern)
 po=_capture(text,KEYWORDS["po_no"],id_pattern)
 date=_date(text)
 invoice=re.sub(r"\s+","",invoice or "") or None
 po=re.sub(r"\s+","",po or "") or None
 vendors=db.query(models.VendorModel).all()
 gst_pattern=r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b"
 gstins={re.sub(r"[^A-Z0-9]","",g.upper()) for g in re.findall(gst_pattern,text,re.I)}
 gst_hits=[v for v in vendors if re.sub(r"[^A-Z0-9]","",(v.gst_no or "").upper()) in gstins and v.gst_no]
 vendor_match=gst_hits[0] if len(gst_hits)==1 else None
 vendor_text=_capture(text,KEYWORDS["vendor"],r"[^\n]{2,100}")
 if not vendor_text:
  ignored=re.compile(r"invoice|bill\s*no|gstin|date|dated|phone|mobile|email|www|page|amount|buyer|consignee|ship\s*to|bill\s*to|purchase\s*order|description|quantity|rate|total|tax invoice",re.I)
  for line in text.splitlines()[:12]:
   line=re.sub(r"\s+"," ",line).strip(" :|-")
   if 4<=len(line)<=90 and re.search(r"[A-Za-z]{3,}",line) and not ignored.search(line):
    vendor_text=line; break
 if not vendor_match and vendor_text:
  candidate=_norm(vendor_text); ranked=[]
  for v in vendors:
   name=_norm(v.name)
   if len(name)<5: continue
   ratio=SequenceMatcher(None,candidate,name).ratio()
   a=set(re.findall(r"[a-z0-9]{3,}",candidate)); b=set(re.findall(r"[a-z0-9]{3,}",name))
   score=max(ratio,len(a&b)/max(1,len(b))*.92,1.0 if name in candidate else 0.0)
   if score>=.80: ranked.append((score,v))
  ranked.sort(key=lambda x:x[0],reverse=True)
  if ranked and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>=.10): vendor_match=ranked[0][1]
 return {"invoice_no":invoice,"po_no":po,"grn_date":date,"vendor_code":vendor_match.code if vendor_match else None,"vendor_name":vendor_match.name if vendor_match else vendor_text}

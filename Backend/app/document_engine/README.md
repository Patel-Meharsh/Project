# Local Document Engine

This package contains reusable, deterministic Python processing stages for
business documents. It is designed to support GRNs first and later be reused
for purchase orders, delivery challans and similar documents.

## Processing stages

1. **Digital PDF text** — `extract_pdf_text_sources()` reads embedded text
   page-by-page and attempts table extraction with pdfplumber.
2. **Image preparation and OCR** — `prepare_ocr_variants()` preprocesses scans;
   `run_ocr_candidates()` runs local Tesseract and selects the strongest
   candidate. PaddleOCR is optional and is only initialized when all three
   local model directories are configured.
3. **Layout understanding** — `group_words_into_rows()` and `rows_to_text()`
   rebuild visual rows from OCR word coordinates.
4. **Contextual matching** — `normalize_alphanumeric()` and
   `rank_candidates()` compare extracted descriptions with trusted master data.
5. **Validation** — `line_item_warnings()` and `score_line_item_rows()`
   flag incomplete values and arithmetic inconsistencies without silently
   rewriting invoice quantities, rates or amounts.

## Design constraints

- No hosted AI, LLM, cloud OCR or external AI API calls.
- OCR and image processing run locally on the backend.
- PDF extraction and OCR produce evidence; GRN-specific code maps that evidence
  to vendor/item masters and the editable review draft.
- Uncertain values must remain reviewable. Validation must not silently replace
  supplier invoice values with catalog defaults.
- Document-specific field rules should be added as profiles/adapters rather
  than hardcoded sample-invoice records.

## Runtime dependencies

Digital PDFs use pypdf and pdfplumber. Scanned PDFs/images use PyMuPDF, Pillow,
pytesseract and the locally installed Tesseract executable. OpenCV improves
preprocessing. PaddleOCR is optional and requires pre-downloaded local model
directories; it must not download models at runtime.

"""Compare PDF text/table extraction and OCR engines on sample GRN documents.

Run from Backend:
    python scripts/benchmark_grn_ocr.py path/to/invoice.pdf
    python scripts/benchmark_grn_ocr.py path/to/invoice.jpg

This is an offline evaluation helper. It does not modify the production extraction
endpoint, save GRNs, or update inventory. Review outputs against the original invoice.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import pymupdf


def read_pymupdf_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return ""
    with pymupdf.open(path) as document:
        return "\n\n".join(page.get_text("text") or "" for page in document)


def read_pdfplumber(path: Path) -> tuple[str, str]:
    if path.suffix.lower() != ".pdf":
        return "", "PDF table extraction skipped for image input."
    import pdfplumber

    text_pages: list[str] = []
    table_pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text_pages.append(f"--- Page {page_number} ---\n{page.extract_text() or ''}")
            tables = page.extract_tables() or []
            for table_number, table in enumerate(tables, start=1):
                table_pages.append(
                    f"--- Page {page_number}, Table {table_number} ---\n"
                    + "\n".join(" | ".join((cell or "").strip() for cell in row) for row in table)
                )
    return "\n\n".join(text_pages), "\n\n".join(table_pages) or "No tables detected."


def render_pdf_pages(path: Path, directory: Path) -> list[Path]:
    rendered: list[Path] = []
    with pymupdf.open(path) as document:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            image_path = directory / f"page_{index + 1}.png"
            pixmap.save(image_path)
            rendered.append(image_path)
    return rendered


def run_tesseract(image_paths: list[Path]) -> str:
    import pytesseract
    from PIL import Image

    outputs = []
    for path in image_paths:
        with Image.open(path) as image:
            outputs.append(f"--- {path.name} ---\n{pytesseract.image_to_string(image)}")
    return "\n\n".join(outputs)


def run_paddleocr(image_paths: list[Path]) -> str:
    from paddleocr import PaddleOCR

    # Initialize once and reuse for all pages in this document.
    engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    outputs = []
    for path in image_paths:
        result = engine.ocr(str(path), cls=True) or []
        lines = []
        for page_result in result:
            for entry in page_result or []:
                try:
                    recognized_text = entry[1][0]
                    confidence = float(entry[1][1])
                    lines.append(f"{recognized_text} [confidence={confidence:.3f}]")
                except (IndexError, TypeError, ValueError):
                    continue
        outputs.append(f"--- {path.name} ---\n" + "\n".join(lines))
    return "\n\n".join(outputs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="PDF, JPG/JPEG, or PNG invoice")
    args = parser.parse_args()
    path = args.document.expanduser().resolve()
    if not path.is_file():
        parser.error(f"File not found: {path}")
    if path.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
        parser.error("Supported inputs are PDF, JPG/JPEG, and PNG.")

    print("\n========== PyMuPDF embedded text ==========")
    print(read_pymupdf_text(path) or "(No embedded PDF text / image input)")

    if path.suffix.lower() == ".pdf":
        print("\n========== pdfplumber text ==========")
        pdf_text, tables = read_pdfplumber(path)
        print(pdf_text or "(No text detected)")
        print("\n========== pdfplumber tables ==========")
        print(tables)

    with tempfile.TemporaryDirectory(prefix="grn_ocr_benchmark_") as temp_dir:
        temp_path = Path(temp_dir)
        image_paths = render_pdf_pages(path, temp_path) if path.suffix.lower() == ".pdf" else [path]

        print("\n========== Tesseract OCR ==========")
        try:
            print(run_tesseract(image_paths) or "(No OCR text detected)")
        except Exception as exc:
            print(f"Tesseract failed: {type(exc).__name__}: {exc}")

        print("\n========== PaddleOCR ==========")
        try:
            print(run_paddleocr(image_paths) or "(No OCR text detected)")
        except Exception as exc:
            print(f"PaddleOCR failed: {type(exc).__name__}: {exc}")

    print("\n========== Evaluation reminder ==========")
    print(
        "Compare each output with the source invoice: item description, quantity, UOM, "
        "rate, amount, and row boundaries. A text output that looks readable can still "
        "have incorrect column associations. Do not select a winner based on text length."
    )


if __name__ == "__main__":
    main()

"""PDF upload handling, text extraction (with OCR fallback), cleaning and chunking."""
import logging
import re
import uuid
from pathlib import Path

from backend import database as db
from backend.config import Config

log = logging.getLogger("campusai.processor")

try:  # preferred extractor
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


# --------------------------------------------------------------- uploading
class InvalidPDF(ValueError):
    pass


def save_pdf(file_storage):
    """Validate and store an uploaded PDF. Returns (stored_name, size_bytes)."""
    name = (file_storage.filename or "").strip()
    if not name.lower().endswith(".pdf"):
        raise InvalidPDF(f"'{name}' is not a PDF file.")
    head = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    if head != b"%PDF-":
        raise InvalidPDF(f"'{name}' does not look like a valid PDF.")
    Config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    path = Config.UPLOAD_DIR / stored_name
    file_storage.save(str(path))
    return stored_name, path.stat().st_size


def title_from_filename(filename):
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", stem).strip().title() or "Untitled Document"


# -------------------------------------------------------------- extraction
def _ocr_available():
    if not Config.OCR_ENABLED:
        return False
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_page_fitz(page):
    import io
    import pytesseract
    from PIL import Image
    pix = page.get_pixmap(dpi=200)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _ocr_page_pdf2image(path, page_no):
    import pytesseract
    from pdf2image import convert_from_path
    imgs = convert_from_path(str(path), dpi=200, first_page=page_no, last_page=page_no)
    return pytesseract.image_to_string(imgs[0]) if imgs else ""


def extract_pages(path):
    """Return (pages, used_ocr) where pages = [(page_number, raw_text), ...]."""
    path = Path(path)
    pages = []
    if fitz is not None:
        with fitz.open(str(path)) as pdf:
            for i, page in enumerate(pdf, start=1):
                pages.append([i, page.get_text("text") or ""])
    elif PdfReader is not None:
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, start=1):
            try:
                pages.append([i, page.extract_text() or ""])
            except Exception as exc:
                log.warning("Could not read page %s of %s: %s", i, path.name, exc)
                pages.append([i, ""])
    else:
        raise RuntimeError("Install PyMuPDF (pip install pymupdf) or pypdf to read PDFs.")

    used_ocr = False
    if _ocr_available():
        for item in pages:
            if len(item[1].strip()) >= Config.OCR_MIN_CHARS_PER_PAGE:
                continue
            try:
                if fitz is not None:
                    with fitz.open(str(path)) as pdf:
                        text = _ocr_page_fitz(pdf[item[0] - 1])
                else:
                    text = _ocr_page_pdf2image(path, item[0])
                if text.strip():
                    item[1] = text
                    used_ocr = True
            except Exception as exc:
                log.warning("OCR failed on page %s of %s: %s", item[0], path.name, exc)
                break  # missing poppler/tesseract: no point retrying every page
    return [(n, t) for n, t in pages], used_ocr


# ---------------------------------------------------------------- cleaning
def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)          # de-hyphenate line breaks
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"[ ]*\n[ ]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- chunking
def split_text(text, size=None, overlap=None):
    size = size or Config.CHUNK_SIZE
    overlap = overlap if overlap is not None else Config.CHUNK_OVERLAP
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # prefer to break at a paragraph, then sentence, then space
            window = text[start:end]
            for sep in ("\n\n", "\n", ". ", " "):
                idx = window.rfind(sep)
                if idx > size * 0.5:
                    end = start + idx + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_pages(pages):
    """pages = [(page_no, cleaned_text)] -> [{text, page, chunk_index}]"""
    out, idx = [], 0
    for page_no, text in pages:
        for piece in split_text(text):
            out.append({"text": piece, "page": page_no, "chunk_index": idx})
            idx += 1
    return out


# ------------------------------------------------------------ orchestration
def process_document(doc_id, vector_store):
    """Extract -> clean -> chunk -> embed -> index. Updates the document status."""
    doc = db.get_document(doc_id)
    if not doc:
        return
    path = Config.UPLOAD_DIR / doc["stored_name"]
    try:
        db.update_document(doc_id, status="processing", error=None)
        raw_pages, used_ocr = extract_pages(path)
        pages = [(n, clean_text(t)) for n, t in raw_pages]
        pages = [(n, t) for n, t in pages if t]
        if not pages:
            msg = "No readable text found."
            if not Config.OCR_ENABLED or not _ocr_available():
                msg += " This looks like a scanned PDF; install Tesseract OCR to enable OCR."
            raise RuntimeError(msg)
        full_text = "\n\n".join(f"[Page {n}]\n{t}" for n, t in pages)
        chunks = chunk_pages(pages)
        rows = db.replace_document_chunks(doc_id, doc["title"], chunks)
        vector_store.remove(document_id=doc_id)
        vector_store.add(rows)
        db.update_document(doc_id, status="ready", pages=len(raw_pages),
                           extracted_text=full_text, used_ocr=int(used_ocr), error=None)
        log.info("Processed document %s (%s chunks)", doc_id, len(rows))
    except Exception as exc:
        log.exception("Processing failed for document %s", doc_id)
        db.update_document(doc_id, status="failed", error=str(exc)[:500])

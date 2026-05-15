import io
import os
import sys


def _configure_tesseract():
    if not getattr(sys, 'frozen', False):
        return
    exe_dir = os.path.dirname(sys.executable)
    tesseract_cmd = os.path.join(exe_dir, 'Tesseract-OCR', 'tesseract.exe')
    if os.path.exists(tesseract_cmd):
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


_configure_tesseract()


def ocr_page(fitz_page):
    import pytesseract
    from PIL import Image

    try:
        pixmap = fitz_page.get_pixmap(dpi=300)
    except Exception:
        return ""

    try:
        img = Image.open(io.BytesIO(pixmap.tobytes("png")))
        return pytesseract.image_to_string(img)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract is not installed or not on PATH. "
            "Install with: brew install tesseract (macOS) or apt install tesseract-ocr (Linux)."
        )
    except Exception:
        return ""

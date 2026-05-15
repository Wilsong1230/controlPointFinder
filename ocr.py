import io


def ocr_page(fitz_page):
    import pytesseract
    from PIL import Image

    try:
        pixmap = fitz_page.get_pixmap(dpi=300)
    except Exception:
        return ""

    img = Image.open(io.BytesIO(pixmap.tobytes("png")))
    try:
        return pytesseract.image_to_string(img)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract is not installed or not on PATH. "
            "Install with: brew install tesseract (macOS) or apt install tesseract-ocr (Linux)."
        )

from receipt_app.ocr.base import OCRBackend
from receipt_app.ocr.tesseract_backend import TesseractOCRBackend

DEFAULT_OCR_BACKEND = TesseractOCRBackend()


def get_ocr_backend() -> OCRBackend:
    return TesseractOCRBackend()


__all__ = [
    "DEFAULT_OCR_BACKEND",
    "OCRBackend",
    "TesseractOCRBackend",
    "get_ocr_backend",
]

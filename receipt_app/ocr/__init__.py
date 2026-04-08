from __future__ import annotations

from receipt_app.ocr.base import OCRBackend
from receipt_app.ocr.gemini_backend import GeminiOCRBackend


def get_ocr_backend(*, threshold: int = 70) -> OCRBackend:
    return GeminiOCRBackend(threshold=threshold)


DEFAULT_OCR_BACKEND = get_ocr_backend()


__all__ = [
    "DEFAULT_OCR_BACKEND",
    "GeminiOCRBackend",
    "OCRBackend",
    "get_ocr_backend",
]

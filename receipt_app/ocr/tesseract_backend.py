from __future__ import annotations

from dataclasses import dataclass

import pytesseract

from receipt_app.config import DEFAULT_CONFIG
from receipt_app.models import OCRResult, UploadedReceipt
from receipt_app.utils.images import normalize_receipt_image, open_image_from_bytes


@dataclass
class TesseractOCRBackend:
    language: str = DEFAULT_CONFIG.tesseract_languages
    backend_name: str = "tesseract"

    def extract_text(self, receipt: UploadedReceipt) -> OCRResult:
        image = open_image_from_bytes(receipt.image_bytes)
        normalized = normalize_receipt_image(image)
        text = pytesseract.image_to_string(normalized, lang=self.language)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return OCRResult(
            source_file_name=receipt.file_name,
            text=text.strip(),
            backend_name=self.backend_name,
            language=self.language,
            lines=lines,
        )

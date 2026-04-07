from __future__ import annotations

from typing import Protocol

from receipt_app.models import OCRResult, UploadedReceipt


class OCRBackend(Protocol):
    backend_name: str

    def extract_text(self, receipt: UploadedReceipt) -> OCRResult: ...

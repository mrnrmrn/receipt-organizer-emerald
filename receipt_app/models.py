from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal


ReceiptCategory = Literal["meal", "taxi", "coffee", "etc"]


@dataclass
class UploadedReceipt:
    file_name: str
    image_bytes: bytes
    mime_type: str = "image/png"


@dataclass
class OCRResult:
    source_file_name: str
    text: str
    backend_name: str
    receipt_date: date | None = None
    category: ReceiptCategory = "etc"
    amount: Decimal | None = None
    language: str = "kor+eng"
    confidence: float | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class ParsedReceipt:
    source_file_name: str
    raw_text: str
    receipt_date: date | None = None
    category: ReceiptCategory = "etc"
    amount: Decimal | None = None
    notes: str | None = None

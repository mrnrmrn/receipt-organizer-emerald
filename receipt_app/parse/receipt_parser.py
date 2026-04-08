from __future__ import annotations

from dataclasses import dataclass

from receipt_app.models import OCRResult, ParsedReceipt


@dataclass
class ReceiptParser:
    def parse(self, ocr_result: OCRResult) -> ParsedReceipt:
        return ParsedReceipt(
            source_file_name=ocr_result.source_file_name,
            raw_text=ocr_result.text,
            receipt_date=ocr_result.receipt_date,
            category=ocr_result.category,
            amount=ocr_result.amount,
            receipt_box=ocr_result.receipt_box,
            task_name=None,
            notes=None,
        )


def parse_receipt_text(ocr_result: OCRResult) -> ParsedReceipt:
    parser = ReceiptParser()
    return parser.parse(ocr_result)

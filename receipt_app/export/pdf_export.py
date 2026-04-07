from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from receipt_app.models import ParsedReceipt, UploadedReceipt
from receipt_app.utils.images import (
    image_to_pdf_bytes,
    open_image_from_bytes,
    prepare_image_for_pdf,
)


def build_pdf_archive(
    receipts: list[UploadedReceipt],
    parsed_receipts: list[ParsedReceipt],
) -> tuple[bytes, list[str]]:
    filenames: list[str] = []
    output = BytesIO()

    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for receipt, parsed in zip(receipts, parsed_receipts):
            filename = build_pdf_filename(receipt.file_name, parsed)
            pdf_bytes = _receipt_to_pdf_bytes(receipt)
            archive.writestr(filename, pdf_bytes)
            filenames.append(filename)

    return output.getvalue(), filenames


def build_pdf_filename(source_file_name: str, parsed_receipt: ParsedReceipt) -> str:
    date_text = _format_date(parsed_receipt.receipt_date)
    amount_text = _format_amount(parsed_receipt.amount)
    original_name = _sanitize_filename_component(Path(source_file_name).stem)
    return f"{date_text}_{amount_text}_{original_name}.pdf"


def _receipt_to_pdf_bytes(receipt: UploadedReceipt) -> bytes:
    image = open_image_from_bytes(receipt.image_bytes)
    prepared = prepare_image_for_pdf(image)
    return image_to_pdf_bytes(prepared)


def _format_date(value: date | None) -> str:
    if value is None:
        return "unknown-date"
    return value.isoformat()


def _format_amount(value: Decimal | None) -> str:
    if value is None:
        return "unknown-amount"

    normalized = value.quantize(Decimal("1")) if value == value.to_integral_value() else value
    text = format(normalized, "f").rstrip("0").rstrip(".")
    return text or "0"


def _sanitize_filename_component(value: str) -> str:
    collapsed = re.sub(r"\s+", "_", value.strip())
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", collapsed)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("._-") or "receipt"

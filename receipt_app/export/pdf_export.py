from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
import re
from zipfile import ZIP_DEFLATED, ZipFile

from receipt_app.models import ParsedReceipt, UploadedReceipt
from receipt_app.utils.images import (
    binarize_receipt_image,
    image_to_pdf_bytes,
    normalize_receipt_image,
    open_image_from_bytes,
    prepare_image_for_pdf,
)


def build_pdf_archive(
    receipts: list[UploadedReceipt],
    parsed_receipts: list[ParsedReceipt],
    person_name: str,
    threshold: int = 70,
    task_name_by_date: dict[str, str] | None = None,
) -> tuple[bytes, list[str]]:
    filenames: list[str] = []
    output = BytesIO()
    task_name_by_date = task_name_by_date or {}

    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for receipt, parsed in zip(receipts, parsed_receipts):
            filename = build_pdf_filename(
                receipt.file_name,
                parsed,
                person_name=person_name,
                task_name_by_date=task_name_by_date,
            )
            pdf_bytes = _receipt_to_pdf_bytes(
                receipt,
                parsed_receipt=parsed,
                threshold=threshold,
            )
            archive.writestr(filename, pdf_bytes)
            filenames.append(filename)

    return output.getvalue(), filenames


def build_pdf_filename(
    source_file_name: str,
    parsed_receipt: ParsedReceipt,
    person_name: str,
    task_name_by_date: dict[str, str] | None = None,
) -> str:
    task_name_by_date = task_name_by_date or {}
    date_key = parsed_receipt.receipt_date.isoformat() if parsed_receipt.receipt_date else "unknown-date"
    task_name = _sanitize_filename_component(task_name_by_date.get(date_key, ""))
    if not task_name:
        task_name = "untitled-task"
    date_text = _format_date(parsed_receipt.receipt_date)
    person_name_text = _sanitize_filename_component(person_name) or "unknown-name"
    category_text = parsed_receipt.category
    amount_text = _format_amount(parsed_receipt.amount)
    return f"{task_name}_{date_text}_{person_name_text}_{category_text}_{amount_text}.pdf"


def _receipt_to_pdf_bytes(
    receipt: UploadedReceipt,
    parsed_receipt: ParsedReceipt,
    threshold: int,
) -> bytes:
    image = open_image_from_bytes(receipt.image_bytes)
    normalized = normalize_receipt_image(image)
    binarized = binarize_receipt_image(normalized, threshold=threshold)
    prepared = prepare_image_for_pdf(binarized)
    return image_to_pdf_bytes(prepared)


def _format_date(value: date | None) -> str:
    if value is None:
        return "unknown-date"
    return value.strftime("%d%b%Y")


def _format_amount(value: Decimal | None) -> str:
    if value is None:
        return "unknown-amount"
    return str(int(value))


def _sanitize_filename_component(value: str) -> str:
    collapsed = re.sub(r"\s+", "_", value.strip())
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", collapsed)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("._-") or "receipt"

from __future__ import annotations

from datetime import date
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
                task_name_by_date=task_name_by_date,
            )
            pdf_bytes = _receipt_to_pdf_bytes(receipt)
            archive.writestr(filename, pdf_bytes)
            filenames.append(filename)

    return output.getvalue(), filenames


def build_pdf_filename(
    source_file_name: str,
    parsed_receipt: ParsedReceipt,
    task_name_by_date: dict[str, str] | None = None,
) -> str:
    task_name_by_date = task_name_by_date or {}
    date_key = parsed_receipt.receipt_date.isoformat() if parsed_receipt.receipt_date else "unknown-date"
    task_name = _sanitize_filename_component(task_name_by_date.get(date_key, ""))
    if not task_name:
        task_name = "untitled-task"
    date_text = _format_date(parsed_receipt.receipt_date)
    original_name = _sanitize_filename_component(Path(source_file_name).stem)
    return f"{task_name}_{date_text}_{original_name}.pdf"


def _receipt_to_pdf_bytes(receipt: UploadedReceipt) -> bytes:
    image = open_image_from_bytes(receipt.image_bytes)
    prepared = prepare_image_for_pdf(image)
    return image_to_pdf_bytes(prepared)


def _format_date(value: date | None) -> str:
    if value is None:
        return "unknown-date"
    return value.strftime("%d%b%Y")


def _sanitize_filename_component(value: str) -> str:
    collapsed = re.sub(r"\s+", "_", value.strip())
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", collapsed)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("._-") or "receipt"

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

from receipt_app.config import DEFAULT_CONFIG
from receipt_app.models import OCRResult, ReceiptBox, ReceiptCategory, UploadedReceipt
from receipt_app.utils.images import (
    image_to_png_bytes,
    normalize_receipt_image,
    open_image_from_bytes,
)

DEFAULT_GEMINI_PROMPT = (
    "Analyze the receipt image and return a JSON object. "
    "Extract the receipt date when visible. "
    "Extract the final charged amount as digits only when visible. "
    "Choose exactly one category from: meal, taxi, coffee, etc. "
    "Return the full receipt bounding box as [ymin, xmin, ymax, xmax] in normalized 0-1000 coordinates. "
    "The box should tightly cover the receipt paper visible in the image. "
    "Use etc when the receipt does not clearly fit meal, taxi, or coffee. "
    "If the date is missing or unclear, return null for receipt_date. "
    "If the amount is missing or unclear, return null for amount. "
    "If the receipt box is missing or unclear, return null for receipt_box. "
    "receipt_date must use YYYY-MM-DD format."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "receipt_date": {
            "type": ["string", "null"],
            "format": "date",
            "description": "Receipt date in YYYY-MM-DD format, or null if unknown.",
        },
        "category": {
            "type": "string",
            "enum": ["meal", "taxi", "coffee", "etc"],
        },
        "amount": {
            "type": ["string", "null"],
            "description": "Final charged amount as a plain number string like 12800, or null if unknown.",
        },
        "receipt_box": {
            "type": ["array", "null"],
            "items": {"type": "integer"},
            "minItems": 4,
            "maxItems": 4,
            "description": "Full receipt bounding box as [ymin, xmin, ymax, xmax] using 0-1000 normalized coordinates.",
        },
    },
    "required": ["receipt_date", "category", "amount", "receipt_box"],
    "additionalProperties": False,
}


def _read_streamlit_secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        return None

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_streamlit_section_secret(section: str, key: str) -> str | None:
    try:
        value = st.secrets.get(section)
    except Exception:
        return None

    if isinstance(value, Mapping):
        nested_value = value.get(key)
        if isinstance(nested_value, str) and nested_value.strip():
            return nested_value.strip()
    return None


def _get_server_setting(
    *names: str, section: str | None = None, key: str | None = None
) -> str | None:
    for name in names:
        value = _read_streamlit_secret(name)
        if value:
            return value

    if section and key:
        value = _read_streamlit_section_secret(section, key)
        if value:
            return value

    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()

    return None


def _collect_response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts_text: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                parts_text.append(part_text.strip())

    return "\n".join(parts_text).strip()


def _parse_structured_payload(response: object) -> dict[str, object]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed

    text = _collect_response_text(response)
    if not text:
        raise ValueError("Gemini returned an empty structured response.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Gemini structured response must be a JSON object.")

    return payload


def _parse_receipt_date(raw_value: object) -> date | None:
    if raw_value in (None, ""):
        return None
    if not isinstance(raw_value, str):
        raise ValueError("receipt_date must be a string or null.")
    try:
        return date.fromisoformat(raw_value[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid receipt_date format: {raw_value}") from exc


def _parse_category(raw_value: object) -> ReceiptCategory:
    if raw_value not in {"meal", "taxi", "coffee", "etc"}:
        raise ValueError(f"Invalid category returned by Gemini: {raw_value}")
    return raw_value


def _parse_amount(raw_value: object) -> Decimal | None:
    if raw_value in (None, ""):
        return None
    if not isinstance(raw_value, str):
        raise ValueError("amount must be a string or null.")

    normalized = raw_value.replace(",", "").strip()
    if not normalized:
        return None

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount returned by Gemini: {raw_value}") from exc

    if amount < 0:
        raise ValueError(f"Invalid negative amount returned by Gemini: {raw_value}")
    return amount


def _parse_receipt_box(raw_value: object) -> ReceiptBox | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise ValueError("receipt_box must be an array of four integers or null.")

    coords: list[int] = []
    for item in raw_value:
        if not isinstance(item, int):
            raise ValueError("receipt_box coordinates must be integers.")
        coords.append(max(0, min(item, 1000)))

    ymin, xmin, ymax, xmax = coords
    if ymin >= ymax or xmin >= xmax:
        raise ValueError(f"Invalid receipt_box returned by Gemini: {raw_value}")
    return (ymin, xmin, ymax, xmax)


@dataclass
class GeminiOCRBackend:
    model: str | None = None
    prompt: str = DEFAULT_GEMINI_PROMPT
    backend_name: str = "gemini"
    language: str = "ko,en"

    def extract_text(self, receipt: UploadedReceipt) -> OCRResult:
        from google import genai  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
        from google.genai import types  # pyright: ignore[reportMissingImports]

        api_key = _get_server_setting(
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            section="gemini",
            key="api_key",
        )
        if not api_key:
            raise ValueError(
                "Gemini API key is not configured. Set GEMINI_API_KEY in Streamlit secrets or the server environment."
            )

        model = self.model or _get_server_setting(
            "GEMINI_MODEL",
            section="gemini",
            key="model",
        )
        model = model or getattr(DEFAULT_CONFIG, "gemini_model", "gemini-2.5-flash")

        image = open_image_from_bytes(receipt.image_bytes)
        normalized = normalize_receipt_image(image)
        png_bytes = image_to_png_bytes(normalized)

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=self.prompt),
                        types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=RESPONSE_SCHEMA,
            ),
        )

        payload = _parse_structured_payload(response)
        receipt_date = _parse_receipt_date(payload.get("receipt_date"))
        category = _parse_category(payload.get("category"))
        amount = _parse_amount(payload.get("amount"))
        receipt_box = _parse_receipt_box(payload.get("receipt_box"))
        text = json.dumps(
            {
                "receipt_date": receipt_date.isoformat() if receipt_date else None,
                "category": category,
                "amount": str(amount) if amount is not None else None,
                "receipt_box": list(receipt_box) if receipt_box else None,
            },
            ensure_ascii=False,
            indent=2,
        )
        return OCRResult(
            source_file_name=receipt.file_name,
            text=text,
            backend_name=self.backend_name,
            receipt_date=receipt_date,
            category=category,
            amount=amount,
            receipt_box=receipt_box,
            language=self.language,
            lines=[],
        )

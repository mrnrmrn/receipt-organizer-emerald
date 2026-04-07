from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

import streamlit as st

from receipt_app.config import DEFAULT_CONFIG
from receipt_app.models import OCRResult, UploadedReceipt
from receipt_app.utils.images import (
    image_to_png_bytes,
    normalize_receipt_image,
    open_image_from_bytes,
)

DEFAULT_GEMINI_PROMPT = (
    "Extract all visible receipt text in reading order. "
    "Return only the OCR text with line breaks preserved. "
    "Do not summarize, translate, label fields, or add commentary."
)


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
            config=types.GenerateContentConfig(temperature=0),
        )

        text = _collect_response_text(response)
        if not text:
            raise ValueError("Gemini returned an empty OCR response.")

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return OCRResult(
            source_file_name=receipt.file_name,
            text=text,
            backend_name=self.backend_name,
            language=self.language,
            lines=lines,
        )

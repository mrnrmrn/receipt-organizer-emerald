from __future__ import annotations

import importlib
import os

import streamlit as st

from receipt_app.config import DEFAULT_CONFIG
from receipt_app.ocr.base import OCRBackend


def _read_server_backend_name() -> str:
    try:
        secret_value = st.secrets.get("OCR_BACKEND")
    except Exception:
        secret_value = None

    if isinstance(secret_value, str) and secret_value.strip():
        return secret_value.strip().lower()

    env_value = os.getenv("OCR_BACKEND")
    if env_value and env_value.strip():
        return env_value.strip().lower()

    return DEFAULT_CONFIG.ocr_backend.strip().lower()


def get_ocr_backend() -> OCRBackend:
    backend_name = _read_server_backend_name()
    if backend_name == "gemini":
        gemini_module = importlib.import_module("receipt_app.ocr.gemini_backend")
        return gemini_module.GeminiOCRBackend()
    if backend_name == "tesseract":
        from receipt_app.ocr.tesseract_backend import TesseractOCRBackend

        return TesseractOCRBackend()
    raise ValueError(
        f"Unsupported OCR backend '{backend_name}'. Expected one of: gemini, tesseract."
    )


DEFAULT_OCR_BACKEND = get_ocr_backend()


__all__ = [
    "DEFAULT_OCR_BACKEND",
    "OCRBackend",
    "get_ocr_backend",
]

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image


def open_image_from_bytes(image_bytes: bytes) -> Image.Image:
    with BytesIO(image_bytes) as buffer:
        image = Image.open(buffer)
        image.load()
    return image


def image_to_pdf_bytes(image: Image.Image) -> bytes:
    with BytesIO() as buffer:
        image.save(buffer, format="PDF")
        return buffer.getvalue()


def image_bytes_to_pdf_bytes(image_bytes: bytes) -> bytes:
    image = open_image_from_bytes(image_bytes)
    return image_to_pdf_bytes(image.convert("RGB"))


def convert_image_bytes_to_jpeg(
    image_bytes: bytes,
    *,
    quality: int = 88,
) -> bytes:
    image = open_image_from_bytes(image_bytes)
    converted = image.convert("RGB")
    with BytesIO() as buffer:
        converted.save(
            buffer,
            format="JPEG",
            quality=quality,
            optimize=True,
        )
        return buffer.getvalue()


def replace_file_extension_with_jpg(filename: str) -> str:
    stem = Path(filename).stem.strip() or "receipt"
    return f"{stem}.jpg"

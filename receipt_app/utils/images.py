from __future__ import annotations

from io import BytesIO

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

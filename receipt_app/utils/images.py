from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps


def open_image_from_bytes(image_bytes: bytes) -> Image.Image:
    with BytesIO(image_bytes) as buffer:
        image = Image.open(buffer)
        image.load()
    return image


def normalize_receipt_image(image: Image.Image) -> Image.Image:
    normalized = ImageOps.exif_transpose(image)
    grayscale = ImageOps.grayscale(normalized)
    autocontrasted = ImageOps.autocontrast(grayscale)
    return autocontrasted


def prepare_image_for_pdf(image: Image.Image) -> Image.Image:
    normalized = ImageOps.exif_transpose(image)
    return normalized.convert("RGB")
def image_to_png_bytes(image: Image.Image) -> bytes:
    with BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def image_to_pdf_bytes(image: Image.Image) -> bytes:
    with BytesIO() as buffer:
        image.save(buffer, format="PDF")
        return buffer.getvalue()

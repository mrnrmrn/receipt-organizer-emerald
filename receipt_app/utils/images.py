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
    return autocontrasted.point(lambda px: 255 if px >= 185 else 0, mode="L")


def prepare_image_for_pdf(image: Image.Image) -> Image.Image:
    normalized = ImageOps.exif_transpose(image)
    return normalized.convert("RGB")


def crop_image_with_normalized_box(
    image: Image.Image,
    box: tuple[int, int, int, int] | None,
) -> Image.Image:
    normalized = ImageOps.exif_transpose(image)
    if box is None:
        return normalized

    ymin, xmin, ymax, xmax = box
    width, height = normalized.size

    left = _normalized_to_pixel(xmin, width)
    top = _normalized_to_pixel(ymin, height)
    right = _normalized_to_pixel(xmax, width)
    bottom = _normalized_to_pixel(ymax, height)

    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return normalized.crop((left, top, right, bottom))


def _normalized_to_pixel(value: int, length: int) -> int:
    return int(round((max(0, min(value, 1000)) / 1000) * length))


def image_to_png_bytes(image: Image.Image) -> bytes:
    with BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def image_to_pdf_bytes(image: Image.Image) -> bytes:
    with BytesIO() as buffer:
        image.save(buffer, format="PDF")
        return buffer.getvalue()

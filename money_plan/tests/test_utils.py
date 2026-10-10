import os
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from money_plan.utils import MAX_IMAGE_BYTES
from money_plan.utils import ImageError
from money_plan.utils import compress_image


def to_bytes(img: Image.Image, fmt: str = "PNG", **kwargs) -> bytes:
    buf = BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def noisy(width: int, height: int, mode: str = "RGB") -> Image.Image:
    """Random pixels: almost incompressible, the worst case for the size limit."""
    size = width * height * len(mode)
    return Image.frombytes(mode, (width, height), os.urandom(size))


def test_big_noisy_photo_ends_up_under_one_mb_and_1600px_side():
    original = to_bytes(noisy(4000, 3000), "PNG")
    assert len(original) > 10 * MAX_IMAGE_BYTES
    result = compress_image(original)
    assert result.size <= MAX_IMAGE_BYTES
    assert max(result.width, result.height) <= 1600
    assert result.content_type == "image/jpeg"
    assert result.extension == ".jpg"
    assert Image.open(BytesIO(result.data)).format == "JPEG"


def test_small_image_keeps_high_quality_and_size():
    result = compress_image(to_bytes(Image.new("RGB", (300, 200), "navy")))
    assert (result.width, result.height) == (300, 200)
    assert result.quality == 85
    assert result.size < 5_000


def test_transparent_png_becomes_webp_with_alpha():
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
    result = compress_image(to_bytes(img))
    assert result.content_type == "image/webp"
    assert result.extension == ".webp"
    assert Image.open(BytesIO(result.data)).mode in ("RGBA", "RGB")


def test_exif_rotation_applied_and_metadata_dropped():
    img = Image.new("RGB", (400, 200), "green")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise when viewed
    exif[0x010F] = "SecretCamera"
    data = to_bytes(img, "JPEG", exif=exif)
    result = compress_image(data)
    out = Image.open(BytesIO(result.data))
    assert out.size == (200, 400)  # rotated
    assert not out.getexif()  # no EXIF left


def test_custom_limits():
    result = compress_image(
        to_bytes(noisy(1200, 1200)),
        max_bytes=100_000,
        max_side=800,
    )
    assert result.size <= 100_000
    assert max(result.width, result.height) <= 800


def test_accepts_uploaded_file_and_makes_content_file():
    upload = SimpleUploadedFile(
        "photo.png",
        to_bytes(Image.new("RGB", (50, 50), "red")),
    )
    result = compress_image(upload)
    content = result.as_content_file("receipt")
    assert content.name == "receipt.jpg"
    assert content.size == result.size


def test_not_an_image_raises():
    with pytest.raises(ImageError):
        compress_image(b"definitely not an image")


def test_impossible_limit_raises():
    with pytest.raises(ImageError):
        compress_image(to_bytes(noisy(600, 600)), max_bytes=500)

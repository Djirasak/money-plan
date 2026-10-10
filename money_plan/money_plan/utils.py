"""Small shared helpers."""

from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

from django.core.files.base import ContentFile
from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError

MAX_IMAGE_BYTES = 1_000_000  # 1 MB
MAX_IMAGE_SIDE = 1600  # px, longest side
MAX_IMAGE_PIXELS = 50_000_000  # refuse decompression bombs
START_QUALITY = 85
MIN_QUALITY = 40
MIN_SIDE = 200  # never shrink below this while chasing the size limit


class ImageError(ValueError):
    """The file is not an image we can read, or it cannot be made small enough."""


@dataclass(frozen=True)
class CompressedImage:
    data: bytes
    content_type: str
    extension: str  # with the dot, e.g. ".jpg"
    width: int
    height: int
    quality: int

    @property
    def size(self) -> int:
        return len(self.data)

    def as_content_file(self, name: str) -> ContentFile:
        """``name`` without extension -> ContentFile named ``name + extension``."""
        return ContentFile(self.data, name=f"{name}{self.extension}")


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = BytesIO()
    if fmt == "JPEG":
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    else:
        img.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def _best_quality(img: Image.Image, fmt: str, max_bytes: int) -> tuple[bytes, int] | None:
    """Highest quality in [MIN_QUALITY, START_QUALITY] that fits ``max_bytes``."""
    data = _encode(img, fmt, START_QUALITY)
    if len(data) <= max_bytes:
        return data, START_QUALITY
    best: tuple[bytes, int] | None = None
    lo, hi = MIN_QUALITY, START_QUALITY - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        data = _encode(img, fmt, mid)
        if len(data) <= max_bytes:
            best, lo = (data, mid), mid + 1
        else:
            hi = mid - 1
    return best


def compress_image(
    source: bytes | BinaryIO,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_side: int = MAX_IMAGE_SIDE,
) -> CompressedImage:
    """Shrink an uploaded image to at most ``max_bytes`` (default 1 MB).

    * Opaque images become JPEG; images with transparency become WebP.
    * The longest side is limited to ``max_side`` px, EXIF rotation is applied
      and all metadata (e.g. GPS position) is dropped.
    * Quality is lowered first (down to ``MIN_QUALITY``); if that is not enough
      the image is scaled down step by step.
    * Animated images keep only their first frame.

    Raises ``ImageError`` for files that are not readable images.
    """
    if isinstance(source, bytes):
        source = BytesIO(source)
    try:
        with Image.open(source) as opened:
            width, height = opened.size
            if width * height > MAX_IMAGE_PIXELS:
                msg = "Image is too large to process"
                raise ImageError(msg)
            img = ImageOps.exif_transpose(opened)
            img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        msg = "Not a valid image"
        raise ImageError(msg) from exc

    fmt, content_type, ext = (
        ("WEBP", "image/webp", ".webp")
        if _has_alpha(img)
        else ("JPEG", "image/jpeg", ".jpg")
    )
    img = img.convert("RGBA" if fmt == "WEBP" else "RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    while True:
        found = _best_quality(img, fmt, max_bytes)
        if found:
            data, quality = found
            return CompressedImage(data, content_type, ext, *img.size, quality)
        if min(img.size) <= MIN_SIDE:
            msg = "Image cannot be compressed under the size limit"
            raise ImageError(msg)
        img = img.resize(
            (max(MIN_SIDE, int(img.width * 0.85)), max(MIN_SIDE, int(img.height * 0.85))),
            Image.Resampling.LANCZOS,
        )

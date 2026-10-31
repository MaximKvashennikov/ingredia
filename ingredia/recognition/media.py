"""Bounded, metadata-free image preparation in memory."""

import warnings
from collections.abc import Buffer
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from ingredia.recognition.errors import FailureCode, RecognitionFailure

MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000


@dataclass(frozen=True)
class PreparedPhoto:
    """Decoded and re-encoded JPEG without original EXIF or other metadata."""

    data: bytes = field(repr=False)
    media_type: str = "image/jpeg"


def prepare_photo(data: bytes) -> PreparedPhoto:
    """Validate a photo and normalize it without saving media on disk."""
    if not data or len(data) > MAX_INPUT_BYTES:
        raise RecognitionFailure(FailureCode.INVALID_IMAGE)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG"} or image.width * image.height > MAX_PIXELS:
                    raise RecognitionFailure(FailureCode.INVALID_IMAGE)
                image.load()
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                normalized.thumbnail((2048, 2048))
                clean = Image.new("RGB", normalized.size)
                clean.paste(normalized)
                destination = BytesIO()
                clean.save(destination, format="JPEG", quality=88)
                result = destination.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise RecognitionFailure(FailureCode.INVALID_IMAGE) from None
    if len(result) > MAX_INPUT_BYTES:
        raise RecognitionFailure(FailureCode.INVALID_IMAGE)
    return PreparedPhoto(result)


class BoundedPhotoBuffer(BytesIO):
    """Stop a Telegram download before the in-memory limit is exceeded."""

    def write(self, data: Buffer, /) -> int:
        """Refuse a chunk that would exceed the allowed photo size."""
        if self.tell() + memoryview(data).nbytes > MAX_INPUT_BYTES:
            raise RecognitionFailure(FailureCode.INVALID_IMAGE)
        return super().write(data)

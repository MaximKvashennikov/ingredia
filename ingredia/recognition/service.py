"""Photo analysis independent of messaging protocols and provider SDKs."""

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Protocol

from ingredia.logging_config import get_logger
from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.media import PreparedPhoto, prepare_photo
from ingredia.recognition.models import PhotoRecognition
from ingredia.recognition.policy import TrialAdmission


class PhotoRecognizer(Protocol):
    """Port implemented by an image recognition provider."""

    async def recognize(self, photo: PreparedPhoto) -> PhotoRecognition:
        """Return validated observations for a prepared image."""
        ...


class TextRecognizer(Protocol):
    """Port for extracting purchase candidates from untrusted text."""

    async def recognize_text(self, text: str) -> PhotoRecognition:
        """Return grocery observations without storing them."""
        ...


class PhotoTrial:
    """Coordinate admission, image preparation and recognition without persistence."""

    def __init__(
        self,
        recognizer: PhotoRecognizer,
        allowed_user_ids: frozenset[int] | None,
        cooldown_seconds: float = 15,
        clock: Callable[[], float] = monotonic,
        text_recognizer: TextRecognizer | None = None,
        admission: TrialAdmission | None = None,
    ) -> None:
        """Inject the provider and process-local trial policy."""
        self._recognizer = recognizer
        self._text_recognizer = text_recognizer
        self._admission = admission or TrialAdmission(allowed_user_ids, cooldown_seconds, clock)

    async def process(
        self,
        user_id: int,
        message_id: int,
        load_photo: Callable[[], Awaitable[bytes]],
    ) -> PhotoRecognition:
        """Analyze an admitted photo with a bounded lifetime and no storage side effects."""
        try:
            with self._admission.admit(user_id, message_id):
                async with asyncio.timeout(75):
                    data = await load_photo()
                    photo = await asyncio.to_thread(prepare_photo, data)
                    get_logger(__name__).info(
                        "Photo prepared: event=%d normalized_bytes=%d",
                        message_id,
                        len(photo.data),
                    )
                    return await self._recognizer.recognize(photo)
        except TimeoutError:
            raise RecognitionFailure(FailureCode.TIMEOUT) from None

    async def process_text(self, user_id: int, message_id: int, text: str) -> PhotoRecognition:
        """Apply the same admission limits to free-text and photo recognition."""
        if self._text_recognizer is None:
            raise RecognitionFailure(FailureCode.UNAVAILABLE)
        if not text.strip() or len(text) > 4000:
            raise RecognitionFailure(FailureCode.INVALID_RESPONSE)
        try:
            with self._admission.admit(user_id, message_id):
                async with asyncio.timeout(75):
                    return await self._text_recognizer.recognize_text(text)
        except TimeoutError:
            raise RecognitionFailure(FailureCode.TIMEOUT) from None

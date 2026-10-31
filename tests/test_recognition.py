"""Checks for schema invariants, media bounds and reusable trial behavior."""

import asyncio
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from ingredia.recognition.errors import RecognitionFailure
from ingredia.recognition.media import MAX_INPUT_BYTES, BoundedPhotoBuffer, prepare_photo
from ingredia.recognition.models import PhotoRecognition
from ingredia.recognition.service import PhotoTrial


class FakeRecognizer:
    """A recognizer that never accesses an external API."""

    def __init__(self, result):
        """Record call count and an injected result."""
        self.result = result
        self.calls = 0

    async def recognize(self, photo):
        """Return the fake response after verifying that media was normalized."""
        assert photo.media_type == "image/jpeg"
        self.calls += 1
        return self.result


@pytest.mark.parametrize(
    "change",
    [
        {"expiry_date": "2026-11-01", "expiry_evidence": None},
        {"name": None, "needs_clarification": False},
        {"needs_clarification": True, "clarification_question": None},
        {"quantity_per_package": {"value": -1, "unit": "l", "evidence": "1 л"}},
        {"unexpected_command": "delete_inventory"},
    ],
)
def test_schema_rejects_unsupported_facts(recognition, change):
    """Invalid quantities, unsupported dates and hidden fields are rejected."""
    data = recognition.model_dump()
    data["products"][0].update(change)
    with pytest.raises(ValidationError):
        PhotoRecognition.model_validate(data)


def test_image_is_normalized_without_metadata():
    """The provider receives a fresh RGB image without source EXIF."""
    image = Image.new("RGB", (40, 30), "white")
    exif = Image.Exif()
    exif[315] = "private metadata"
    source = BytesIO()
    image.save(source, format="JPEG", exif=exif)
    prepared = prepare_photo(source.getvalue())
    with Image.open(BytesIO(prepared.data)) as clean:
        assert clean.format == "JPEG"
        assert clean.mode == "RGB"
        assert not clean.getexif()
    assert "private metadata" not in repr(prepared)


@pytest.mark.parametrize("data", [b"", b"not an image", b"x" * (MAX_INPUT_BYTES + 1)])
def test_invalid_images_are_rejected(data):
    """Bad or oversized files never reach the model."""
    with pytest.raises(RecognitionFailure) as error:
        prepare_photo(data)
    assert error.value.code == "invalid_image"


def test_stream_download_is_bounded():
    """The limit is enforced before a stream chunk grows the buffer."""
    with BoundedPhotoBuffer() as destination:
        with pytest.raises(RecognitionFailure):
            destination.write(b"x" * (MAX_INPUT_BYTES + 1))
        assert destination.tell() == 0


def test_trial_authorization_and_duplicate_protection(jpeg, recognition):
    """Unauthorized callers and repeated updates cause no additional provider calls."""

    async def run():
        fake = FakeRecognizer(recognition)
        trial = PhotoTrial(fake, frozenset({1}), cooldown_seconds=0)
        downloads = 0

        async def load():
            nonlocal downloads
            downloads += 1
            return jpeg

        with pytest.raises(RecognitionFailure, match="forbidden"):
            await trial.process(2, 1, load)
        assert downloads == 0
        assert await trial.process(1, 1, load) == recognition
        with pytest.raises(RecognitionFailure, match="duplicate"):
            await trial.process(1, 1, load)
        assert downloads == fake.calls == 1

    asyncio.run(run())


def test_open_trial_and_cooldown(jpeg, recognition):
    """Explicit open access works while rapid repeats preserve the model budget."""

    async def run():
        fake = FakeRecognizer(recognition)
        trial = PhotoTrial(fake, None, clock=lambda: 100)

        async def load():
            return jpeg

        await trial.process(123, 1, load)
        with pytest.raises(RecognitionFailure, match="cooldown"):
            await trial.process(123, 2, load)
        assert fake.calls == 1

    asyncio.run(run())


def test_failed_media_does_not_call_provider(recognition):
    """Decoding errors release the trial slot and leave external quota untouched."""

    async def run():
        fake = FakeRecognizer(recognition)
        trial = PhotoTrial(fake, None, cooldown_seconds=0)

        async def load():
            return b"invalid"

        for message_id in (1, 2):
            with pytest.raises(RecognitionFailure, match="invalid_image"):
                await trial.process(1, message_id, load)
        assert fake.calls == 0

    asyncio.run(run())


def test_busy_trial_does_not_start_second_model_call(jpeg, recognition):
    """Concurrent photos cannot create a second in-flight provider request."""

    async def run():
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowRecognizer(FakeRecognizer):
            async def recognize(self, photo):
                self.calls += 1
                started.set()
                await release.wait()
                return self.result

        fake = SlowRecognizer(recognition)
        trial = PhotoTrial(fake, None, cooldown_seconds=0)

        async def load():
            return jpeg

        first = asyncio.create_task(trial.process(1, 1, load))
        await started.wait()
        with pytest.raises(RecognitionFailure, match="busy"):
            await trial.process(2, 2, load)
        release.set()
        assert await first == recognition
        assert fake.calls == 1

    asyncio.run(run())

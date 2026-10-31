"""Implement the domain photo recognizer using typed Z.ai requests."""

import httpx
from pydantic import SecretStr

from ingredia.adapters.zai.client import ZaiClient
from ingredia.adapters.zai.models import (
    ImagePart,
    ImageURL,
    SystemMessage,
    TextPart,
    UserMessage,
    VisionRequest,
)
from ingredia.adapters.zai.output import parse_observations
from ingredia.adapters.zai.prompting import render_photo_prompt
from ingredia.recognition.media import PreparedPhoto
from ingredia.recognition.models import PhotoRecognition


class ZaiPhotoRecognizer:
    """Compose prompting, provider transport and output validation."""

    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr) -> None:
        """Use the HTTP client's lifecycle managed by the application."""
        self._api = ZaiClient(client, api_key)

    async def recognize(self, photo: PreparedPhoto) -> PhotoRecognition:
        """Extract observations with one request to the selected free vision model."""
        request = VisionRequest(
            messages=(
                SystemMessage(content=render_photo_prompt()),
                UserMessage(
                    content=[
                        TextPart(text="Распознай продукты на этой фотографии."),
                        ImagePart(image_url=ImageURL.from_photo(photo)),
                    ]
                ),
            )
        )
        completion = await self._api.complete(request)
        return parse_observations(completion)

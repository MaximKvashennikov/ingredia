"""Implement the photo and text recognition ports with one Groq/Qwen adapter."""

import httpx
from pydantic import SecretStr

from ingredia.adapters.chat_completions.models import (
    ImagePart,
    ImageURL,
    PurchaseTextMessage,
    SystemMessage,
    TextPart,
    UserMessage,
)
from ingredia.adapters.chat_completions.output import parse_observations
from ingredia.adapters.groq.client import GroqClient
from ingredia.adapters.groq.models import GroqRequest, JsonObjectFormat
from ingredia.recognition.media import PreparedPhoto
from ingredia.recognition.models import PhotoRecognition
from ingredia.recognition.prompting import render_prompt


class GroqRecognizer:
    """Return the same validated observations used by the existing inventory flow."""

    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr) -> None:
        """Inject shared HTTP lifecycle and provider-specific credentials."""
        self._api = GroqClient(client, api_key)

    async def recognize(self, photo: PreparedPhoto) -> PhotoRecognition:
        """Extract images using JSON mode; reject schema violations locally."""
        request = GroqRequest(
            response_format=JsonObjectFormat(),
            messages=(
                SystemMessage(content=render_prompt("food_photo")),
                UserMessage(
                    content=[
                        TextPart(text="Распознай продукты на этой фотографии."),
                        ImagePart(image_url=ImageURL.from_photo(photo)),
                    ]
                ),
            ),
        )
        return parse_observations(await self._api.complete(request))

    async def recognize_text(self, text: str) -> PhotoRecognition:
        """Extract free-text groceries through the same domain contract."""
        request = GroqRequest(
            messages=(
                SystemMessage(content=render_prompt("purchase_text", schema_in_response=True)),
                PurchaseTextMessage(content=text),
            )
        )
        return parse_observations(await self._api.complete(request))

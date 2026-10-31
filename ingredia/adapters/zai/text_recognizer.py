"""Extract grocery candidates from free text with the selected free cloud model."""

import httpx
from pydantic import SecretStr

from ingredia.adapters.zai.client import ZaiClient
from ingredia.adapters.zai.models import PurchaseTextMessage, PurchaseTextRequest, SystemMessage
from ingredia.adapters.zai.output import parse_observations
from ingredia.recognition.models import PhotoRecognition
from ingredia.recognition.prompting import render_prompt


class ZaiTextRecognizer:
    """Keep text prompting, provider transport and output validation separate."""

    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr) -> None:
        """Inject shared HTTP lifecycle and masked credentials."""
        self.api = ZaiClient(client, api_key)
        self.prompt = render_prompt("purchase_text")

    async def recognize_text(self, text: str) -> PhotoRecognition:
        """Return validated candidates, never execute inventory changes."""
        request = PurchaseTextRequest(
            messages=(
                SystemMessage(content=self.prompt),
                PurchaseTextMessage(content=text),
            )
        )
        return parse_observations(await self.api.complete(request))

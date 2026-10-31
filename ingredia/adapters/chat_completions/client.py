"""Bounded HTTP transport without provider selection or automatic retries."""

from collections.abc import Callable

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from ingredia.adapters.chat_completions.models import VisionCompletion
from ingredia.recognition.errors import FailureCode, RecognitionFailure

MAX_RESPONSE_BYTES = 256 * 1024


async def read_bounded(response: httpx.Response) -> bytes:
    """Reject a response before its body exceeds the memory budget."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
            raise RecognitionFailure(FailureCode.INVALID_RESPONSE)
        body.extend(chunk)
    return bytes(body)


class ChatCompletionClient:
    """Share serialization and transport while keeping provider error rules injected."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: SecretStr,
        endpoint: str,
        failure: Callable[[int, bytes], RecognitionFailure],
    ) -> None:
        """Inject a fixed trusted route and a safe provider-specific error mapper."""
        self._client = client
        self._key = api_key
        self._endpoint = endpoint
        self._failure = failure

    async def complete(self, request: BaseModel) -> VisionCompletion:
        """Issue exactly one request; never retry, follow redirects or choose a fallback."""
        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                json=request.model_dump(mode="json", by_alias=True),
                headers={"Authorization": f"Bearer {self._key.get_secret_value()}"},
                timeout=httpx.Timeout(60, connect=10),
                follow_redirects=False,
            ) as response:
                body = await read_bounded(response)
                if response.status_code != 200:
                    raise self._failure(response.status_code, body)
        except httpx.TimeoutException:
            raise RecognitionFailure(FailureCode.TIMEOUT) from None
        except httpx.HTTPError:
            raise RecognitionFailure(FailureCode.UNAVAILABLE) from None
        try:
            return VisionCompletion.model_validate_json(body)
        except ValidationError:
            raise RecognitionFailure(FailureCode.INVALID_RESPONSE) from None

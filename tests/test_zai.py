"""Z.ai HTTP contract checks with no live network access."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from ingredia.adapters.zai import ZaiPhotoRecognizer
from ingredia.adapters.zai.constants import ENDPOINT, MAX_RESPONSE_BYTES, VISION_MODEL
from ingredia.recognition.errors import RecognitionFailure
from ingredia.recognition.media import prepare_photo


def test_zai_request_and_validated_result(jpeg, recognition):
    """Send only the chosen free model and validate its structured response."""

    async def run():
        requests = []

        def handle(request):
            requests.append(request)
            payload = json.loads(request.content)
            assert str(request.url) == ENDPOINT
            assert payload["model"] == VISION_MODEL
            assert payload["thinking"] == {"type": "disabled"}
            assert payload["messages"][1]["content"][1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"
            )
            assert "tools" not in payload
            assert "response_format" not in payload
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": recognition.model_dump_json()},
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            adapter = ZaiPhotoRecognizer(client, SecretStr("fake-key"))
            result = await adapter.recognize(prepare_photo(jpeg))
        assert result == recognition
        assert result.products[0].quantity_per_package.value == 1
        assert result.products[0].package_count == 2
        assert len(requests) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "credentials"),
        (403, "credentials"),
        (429, "quota"),
        (400, "model_unavailable"),
        (500, "unavailable"),
    ],
)
def test_provider_failures_do_not_leak_or_retry(jpeg, status, code):
    """Preserve the error category without exposing provider messages or retrying."""

    async def run():
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(
                status,
                json={
                    "error": {"code": 1004, "message": "sensitive-provider-message"},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(RecognitionFailure) as error:
                await ZaiPhotoRecognizer(client, SecretStr("fake-key")).recognize(
                    prepare_photo(jpeg)
                )
        assert error.value.code == code
        assert error.value.provider_code == "1004"
        assert "sensitive-provider-message" not in str(error.value)
        assert "fake-key" not in str(error.value)
        assert calls == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"x" * (MAX_RESPONSE_BYTES + 1),
        json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"products": [], "warnings": []}'},
                    }
                ]
            }
        ).encode(),
        json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"products": [], "warnings": [], "command": "delete"}'
                        },
                    }
                ]
            }
        ).encode(),
    ],
)
def test_malformed_or_truncated_responses_are_rejected(jpeg, body):
    """Do not return partial observations or execute extra fields."""

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RecognitionFailure, match="invalid_response"):
                await ZaiPhotoRecognizer(client, SecretStr("fake-key")).recognize(
                    prepare_photo(jpeg)
                )

    asyncio.run(run())


def test_network_timeout_is_safe(jpeg):
    """A transport timeout becomes a stable safe error."""

    async def run():
        def handle(request):
            raise httpx.ReadTimeout("sensitive address", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(RecognitionFailure, match="timeout"):
                await ZaiPhotoRecognizer(client, SecretStr("fake-key")).recognize(
                    prepare_photo(jpeg)
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    ("business_code", "category"),
    [
        (1305, "provider_busy"),
        (1113, "billing"),
    ],
)
def test_business_error_categories(jpeg, business_code, category):
    """An overload is not reported as a consumed quota or an authentication failure."""

    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                429,
                json={"error": {"code": business_code, "message": "private body"}},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RecognitionFailure) as error:
                await ZaiPhotoRecognizer(client, SecretStr("fake-key")).recognize(
                    prepare_photo(jpeg)
                )
        assert error.value.code == category
        assert error.value.provider_code == str(business_code)

    asyncio.run(run())

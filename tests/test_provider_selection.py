"""Provider selection and shared recognition ports without live model requests."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from ingredia.adapters.chat_completions.client import MAX_RESPONSE_BYTES
from ingredia.providers import create_recognizers
from ingredia.recognition.errors import RecognitionFailure
from ingredia.recognition.media import prepare_photo
from ingredia.runtime import run_photo_trial
from ingredia.settings import Settings
from ingredia.settings.ai import AISettings, ProviderCredentials
from ingredia.settings.telegram import TelegramSettings, UserBotSettings


def settings(provider, **credentials):
    """Create nested synthetic configuration without loading the private dotenv file."""
    return Settings(
        _env_file=None,
        telegram=TelegramSettings(
            user=UserBotSettings(
                token=SecretStr("123456:TEST"),
                username="trial_bot",
            )
        ),
        ai=AISettings(
            provider=provider,
            **{name: ProviderCredentials(api_key=key) for name, key in credentials.items()},
        ),
    )


@pytest.mark.parametrize("provider", ["zai", "groq"])
def test_both_providers_implement_photo_and_text_ports(provider, jpeg, recognition):
    """Switch provider without changing the application result or requiring an inactive key."""

    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            payload = json.loads(request.content)
            assert request.headers["authorization"] == "Bearer synthetic-selected-key"
            if provider == "groq":
                assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
                assert payload["model"] == "qwen/qwen3.8-27b"
                assert payload["reasoning_effort"] == "none"
                assert "thinking" not in payload and "max_tokens" not in payload
                if isinstance(payload["messages"][1]["content"], list):
                    assert payload["response_format"] == {"type": "json_object"}
                    assert '"products"' in payload["messages"][0]["content"]
                else:
                    schema = payload["response_format"]["json_schema"]
                    assert schema["strict"] is True
                    assert "schema" in schema and "schema_value" not in schema
                    assert schema["schema"]["additionalProperties"] is False
            else:
                assert str(request.url) == "https://api.z.ai/api/paas/v4/chat/completions"
                assert payload["model"] in {"glm-4.6v-flash", "glm-4.7-flash"}
                assert payload["thinking"] == {"type": "disabled"}
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

        key = "groq" if provider == "groq" else "zai"
        config = settings(provider, **{key: SecretStr("synthetic-selected-key")})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            ports = create_recognizers(config, client)
            assert await ports.photo.recognize(prepare_photo(jpeg)) == recognition
            assert await ports.text.recognize_text("Купил два литра молока") == recognition
        photo = json.loads(calls[0].content)
        assert photo["messages"][1]["content"][1]["image_url"]["url"].startswith(
            "data:image/jpeg;base64,"
        )
        assert len(calls) == 2

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["groq", "zai"])
@pytest.mark.parametrize("empty", [None, ""])
def test_selected_provider_requires_its_own_key(provider, empty):
    """A missing key fails configuration instead of silently selecting the other adapter."""

    async def run():
        keys = {"groq": SecretStr("other"), "zai": SecretStr("other")}
        selected = "groq" if provider == "groq" else "zai"
        keys[selected] = None if empty is None else SecretStr(empty)
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match=selected.upper()):
                create_recognizers(settings(provider, **keys), client)

    asyncio.run(run())


def test_unknown_provider_is_rejected():
    """A typo cannot select an unexpected provider or endpoint."""
    with pytest.raises(ValidationError):
        settings("unknown")


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, "model_unavailable"),
        (401, "credentials"),
        (402, "billing"),
        (403, "credentials"),
        (422, "invalid_response"),
        (429, "quota"),
        (503, "provider_busy"),
        (500, "unavailable"),
    ],
)
def test_groq_errors_never_leak_or_trigger_glm_fallback(status, category):
    """Provider errors are safe and generate exactly one request to the selected endpoint."""

    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(
                status,
                json={
                    "error": {
                        "code": "private_code",
                        "message": "private text and synthetic-key",
                    }
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            ports = create_recognizers(
                settings(
                    "groq",
                    groq=SecretStr("synthetic-key"),
                    zai=SecretStr("inactive-key"),
                ),
                client,
            )
            with pytest.raises(RecognitionFailure) as error:
                await ports.text.recognize_text("Молоко")
        assert error.value.code == category
        assert error.value.provider_code is None
        assert "private" not in str(error.value) and "synthetic-key" not in str(error.value)
        assert len(calls) == 1
        assert calls[0].url.host == "api.groq.com"

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"products":[],"warnings":[]}'},
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"products":[],"warnings":[],"command":"delete"}'},
                    }
                ]
            },
        ),
    ],
)
def test_groq_output_is_validated_locally(response):
    """Even a provider with strict output must pass local bounds and domain validation."""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response)
        ) as client:
            ports = create_recognizers(settings("groq", groq=SecretStr("synthetic")), client)
            with pytest.raises(RecognitionFailure, match="invalid_response"):
                await ports.text.recognize_text("Молоко")

    asyncio.run(run())


def test_groq_redirect_cannot_forward_credentials():
    """A provider redirect cannot send a key or payload to a different host."""

    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "https://untrusted.invalid"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), follow_redirects=True
        ) as client:
            ports = create_recognizers(settings("groq", groq=SecretStr("synthetic")), client)
            with pytest.raises(RecognitionFailure):
                await ports.text.recognize_text("Молоко")
        assert len(calls) == 1

    asyncio.run(run())


def test_groq_transport_timeout_has_no_fallback():
    """A network timeout becomes a safe failure without invoking GLM."""

    async def run():
        def handle(request):
            raise httpx.ReadTimeout("private-url", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            ports = create_recognizers(settings("groq", groq=SecretStr("synthetic")), client)
            with pytest.raises(RecognitionFailure, match="timeout"):
                await ports.text.recognize_text("Молоко")

    asyncio.run(run())


def test_missing_provider_key_fails_before_telegram(monkeypatch):
    """Provider configuration is checked before connecting a real bot."""
    import ingredia.runtime as runtime

    def forbidden_bot(**kwargs):
        raise AssertionError("Telegram must not be initialized")

    monkeypatch.setattr(runtime, "Bot", forbidden_bot)

    async def run():
        with pytest.raises(RuntimeError, match="AI__GROQ__API_KEY"):
            async with run_photo_trial(settings("groq")):
                pytest.fail("An invalid provider configuration started the runtime")

    asyncio.run(run())


def test_vision_schema_rejection_is_logged_without_provider_payload(caplog, jpeg):
    """Reproduce the actual Groq failure category without retaining image or failed output."""

    async def run():
        def reject(request):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "json_validate_failed",
                        "message": "private model content",
                        "failed_generation": "synthetic-private-image-description",
                    }
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            ports = create_recognizers(settings("groq", groq=SecretStr("fake-key")), client)
            with pytest.raises(RecognitionFailure) as error:
                await ports.photo.recognize(prepare_photo(jpeg))
        assert error.value.code == "invalid_response"
        assert "http_status=400" in caplog.text and "code=json_validate_failed" in caplog.text
        assert "private model content" not in caplog.text
        assert "synthetic-private-image-description" not in caplog.text

    asyncio.run(run())


def test_unknown_provider_code_is_not_copied_to_logs(caplog):
    """A syntactically valid code still cannot smuggle private content into diagnostics."""
    from ingredia.adapters.groq.errors import provider_failure

    provider_failure(400, b'{"error":{"code":"synthetic-private-key"}}')
    assert "synthetic-private-key" not in caplog.text and "code=other" in caplog.text


def test_json_mode_photo_still_rejects_invalid_domain_data(jpeg):
    """Provider JSON syntax guarantees do not replace local bounds and evidence validation."""

    async def run():
        def respond(request):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"products":[{"name":"invented"}],"warnings":[]}'
                            },
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            ports = create_recognizers(settings("groq", groq=SecretStr("fake-key")), client)
            with pytest.raises(RecognitionFailure) as error:
                await ports.photo.recognize(prepare_photo(jpeg))
        assert error.value.code == "invalid_response"

    asyncio.run(run())

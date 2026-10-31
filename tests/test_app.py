"""FastAPI lifecycle checks with fake Telegram and provider clients."""

import asyncio
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

import ingredia.app as app_module
import ingredia.runtime as runtime_module
from ingredia.settings import Settings
from ingredia.settings.ai import AISettings, ProviderCredentials
from ingredia.settings.telegram import TelegramSettings, TrialSettings, UserBotSettings


def test_lifespan_starts_and_stops_polling(monkeypatch):
    """The app starts one poller, reports health and closes Telegram on shutdown."""
    state = {"closed": False, "started": 0}
    started = asyncio.Event()

    class FakeSession:
        async def close(self):
            state["closed"] = True

    class FakeBot:
        def __init__(self, **kwargs):
            self.session = FakeSession()

        async def get_me(self):
            return SimpleNamespace(username="trial_bot")

        async def get_webhook_info(self):
            return SimpleNamespace(url="")

    class FakeDispatcher:
        async def start_polling(self, bot, **kwargs):
            state["started"] += 1
            started.set()
            assert kwargs["handle_as_tasks"] is False
            await asyncio.Event().wait()

    monkeypatch.setattr(runtime_module, "Bot", FakeBot)
    monkeypatch.setattr(runtime_module, "create_dispatcher", lambda trial: FakeDispatcher())
    config = Settings(
        _env_file=None,
        telegram=TelegramSettings(
            user=UserBotSettings(token=SecretStr("123456:TEST"), username="trial_bot"),
            trial=TrialSettings(open_access=True),
        ),
        ai=AISettings(zai=ProviderCredentials(api_key=SecretStr("fake-key"))),
    )
    application = app_module.create_app(config)

    async def run():
        async with application.router.lifespan_context(application):
            await asyncio.wait_for(started.wait(), timeout=2)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://test",
            ) as client:
                response = await client.get("/health")
                assert response.status_code == 200
                assert response.json() == {"status": "ok"}
                assert (await client.get("/health/admin")).status_code == 503
                assert state["started"] == 1
                assert state["closed"] is False
        assert state["closed"] is True

    asyncio.run(run())

"""FastAPI routes and lifecycle for the scoped photo trial."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ingredia.runtime import TrialRuntime, run_photo_trial
from ingredia.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Start the injected trial runtime when the application enters its lifespan."""
    config: Settings = application.state.settings or get_settings()
    async with run_photo_trial(config) as runtime:
        application.state.trial_runtime = runtime
        yield


async def health(request: Request) -> JSONResponse:
    """Expose local polling state without user data, secrets or provider requests."""
    runtime: TrialRuntime = request.app.state.trial_runtime
    status, code = ("ok", 200) if runtime.is_running else ("polling_stopped", 503)
    return JSONResponse({"status": status}, status_code=code)


async def admin_health(request: Request) -> JSONResponse:
    """Report administrative transport separately from user polling."""
    runtime: TrialRuntime = request.app.state.trial_runtime
    active = runtime.admin_task is not None and not runtime.admin_task.done()
    return JSONResponse(
        {"status": "ok" if active else "admin_unavailable"},
        status_code=200 if active else 503,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application without opening network clients during module import."""
    application = FastAPI(title="ingredia", lifespan=lifespan)
    application.state.settings = settings
    application.add_api_route("/health", health, methods=["GET"], response_model=None)
    application.add_api_route("/health/admin", admin_health, methods=["GET"], response_model=None)
    return application

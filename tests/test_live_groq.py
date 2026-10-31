"""Explicit, single-request synthetic-image diagnostic, excluded from ordinary QA."""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from ingredia.adapters.groq import GroqRecognizer
from ingredia.recognition.media import prepare_photo
from ingredia.settings import get_settings


@pytest.mark.skipif(
    os.getenv("RUN_GROQ_SMOKE") != "1", reason="Real free-tier quota probe is opt-in"
)
def test_live_synthetic_photo_contract():
    """Diagnose image transport using a generated non-personal project image once."""

    async def run():
        config = get_settings()
        assert config.ai.groq.api_key is not None
        photo = prepare_photo(Path("assets/branding/telegram-avatar-v1.png").read_bytes())
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            result = await GroqRecognizer(client, config.ai.groq.api_key).recognize(photo)
        assert isinstance(result.products, list)
        print("Synthetic image response validated; observed products:", len(result.products))

    asyncio.run(run())

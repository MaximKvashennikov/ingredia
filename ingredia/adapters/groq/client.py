"""Groq-specific routing over the shared bounded chat-completions transport."""

import httpx
from pydantic import SecretStr

from ingredia.adapters.chat_completions.client import ChatCompletionClient
from ingredia.adapters.groq.constants import ENDPOINT
from ingredia.adapters.groq.errors import provider_failure


class GroqClient(ChatCompletionClient):
    """Fix the Groq endpoint and error policy without importing any GLM adapter."""

    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr) -> None:
        """Inject an application-owned network client and masked credentials."""
        super().__init__(client, api_key, ENDPOINT, provider_failure)

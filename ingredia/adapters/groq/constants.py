"""Fixed Groq route and model selected by the user."""

from typing import Final, Literal

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
MODEL: Final[Literal["qwen/qwen3.8-27b"]] = "qwen/qwen3.8-27b"

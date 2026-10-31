"""Compose recognition ports from explicit settings without a silent fallback."""

from dataclasses import dataclass

import httpx

from ingredia.adapters.groq import GroqRecognizer
from ingredia.adapters.groq.recipes import GroqRecipeGenerator
from ingredia.adapters.zai import ZaiPhotoRecognizer
from ingredia.adapters.zai.recipes import ZaiRecipeGenerator
from ingredia.adapters.zai.text_recognizer import ZaiTextRecognizer
from ingredia.recipes.service import RecipeGenerator
from ingredia.recognition.service import PhotoRecognizer, TextRecognizer
from ingredia.settings import Settings


@dataclass(frozen=True)
class RecognitionAdapters:
    """The application sees ports rather than concrete cloud providers."""

    photo: PhotoRecognizer
    text: TextRecognizer
    recipes: RecipeGenerator


def create_recognizers(config: Settings, client: httpx.AsyncClient) -> RecognitionAdapters:
    """Validate only the selected provider; do not contact the network or change the selection."""
    if config.ai.provider == "groq":
        if config.ai.groq.api_key is None or not config.ai.groq.api_key.get_secret_value().strip():
            raise RuntimeError("Set AI__GROQ__API_KEY before selecting AI__PROVIDER=groq")
        adapter = GroqRecognizer(client, config.ai.groq.api_key)
        return RecognitionAdapters(
            adapter, adapter, GroqRecipeGenerator(client, config.ai.groq.api_key)
        )
    if config.ai.zai.api_key is None or not config.ai.zai.api_key.get_secret_value().strip():
        raise RuntimeError("Set AI__ZAI__API_KEY before selecting AI__PROVIDER=zai")
    return RecognitionAdapters(
        ZaiPhotoRecognizer(client, config.ai.zai.api_key),
        ZaiTextRecognizer(client, config.ai.zai.api_key),
        ZaiRecipeGenerator(client, config.ai.zai.api_key),
    )

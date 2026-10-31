"""Load reviewed extraction resources shared by provider adapters."""

import json
from functools import lru_cache
from importlib.resources import files
from string import Template
from typing import Literal

from ingredia.recognition.models import PhotoRecognition


@lru_cache
def prompt_template(kind: Literal["food_photo", "purchase_text"]) -> Template:
    """Resolve only trusted versioned resource names."""
    resource = files("ingredia.recognition").joinpath(f"prompts/{kind}_v1.txt")
    return Template(resource.read_text(encoding="utf-8"))


def render_prompt(
    kind: Literal["food_photo", "purchase_text"],
    schema_in_response: bool = False,
) -> str:
    """Render a fixed extraction prompt with the current domain schema."""
    schema = "Структура задана JSON Schema в response_format запроса."
    if not schema_in_response:
        schema = json.dumps(PhotoRecognition.model_json_schema(), ensure_ascii=False)
    return prompt_template(kind).substitute(schema=schema)

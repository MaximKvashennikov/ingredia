"""Groq-specific structured output and instruct-mode request options."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ingredia.adapters.chat_completions.models import (
    PurchaseTextMessage,
    RecipeInputMessage,
    SystemMessage,
    UserMessage,
)
from ingredia.adapters.groq.constants import MODEL
from ingredia.recognition.models import PhotoRecognition

UNSUPPORTED_CONSTRAINTS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
    }
)


def schema_structure(value: Any) -> Any:
    """Preserve shape while leaving fine-grained domain constraints to Pydantic."""
    if isinstance(value, dict):
        return {
            key: schema_structure(item)
            for key, item in value.items()
            if key not in UNSUPPORTED_CONSTRAINTS
        }
    if isinstance(value, list):
        return [schema_structure(item) for item in value]
    return value


class ObservationSchema(BaseModel):
    """Provider-side structural schema; local validators remain authoritative."""

    name: str = "food_observations"
    strict: Literal[True] = True
    schema_value: dict[str, Any] = Field(
        alias="schema",
        default_factory=lambda: schema_structure(PhotoRecognition.model_json_schema()),
    )


class ResponseFormat(BaseModel):
    """Request strict structured output rather than parsing arbitrary prose."""

    type: Literal["json_schema"] = "json_schema"
    json_schema: ObservationSchema = Field(default_factory=ObservationSchema)


class JsonObjectFormat(BaseModel):
    """Use the documented vision JSON mode while validating the schema locally."""

    type: Literal["json_object"] = "json_object"


class GroqRequest(BaseModel):
    """One bounded Qwen request, with no tools, streaming or hidden retries."""

    model_config = ConfigDict(extra="forbid")
    model: Literal["qwen/qwen3.8-27b"] = MODEL
    messages: tuple[SystemMessage, UserMessage | PurchaseTextMessage | RecipeInputMessage] = Field(
        repr=False
    )
    reasoning_effort: Literal["none"] = "none"
    response_format: ResponseFormat | JsonObjectFormat = Field(default_factory=ResponseFormat)
    max_completion_tokens: int = Field(default=4096, ge=1, le=4096)
    stream: Literal[False] = False

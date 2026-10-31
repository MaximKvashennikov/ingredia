"""Z.ai-specific request options and numeric business error envelopes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ingredia.adapters.chat_completions.models import CompletionChoice as CompletionChoice
from ingredia.adapters.chat_completions.models import CompletionMessage as CompletionMessage
from ingredia.adapters.chat_completions.models import ImagePart as ImagePart
from ingredia.adapters.chat_completions.models import ImageURL as ImageURL
from ingredia.adapters.chat_completions.models import PurchaseTextMessage as PurchaseTextMessage
from ingredia.adapters.chat_completions.models import RecipeInputMessage
from ingredia.adapters.chat_completions.models import SystemMessage as SystemMessage
from ingredia.adapters.chat_completions.models import TextPart as TextPart
from ingredia.adapters.chat_completions.models import UserMessage as UserMessage
from ingredia.adapters.chat_completions.models import VisionCompletion as VisionCompletion
from ingredia.adapters.zai.constants import VISION_MODEL


class ThinkingOptions(BaseModel):
    """Disable optional reasoning for the bounded free-model trial."""

    type: Literal["disabled"] = "disabled"


class VisionRequest(BaseModel):
    """A request restricted to the selected free model with no tools or fallbacks."""

    model_config = ConfigDict(extra="forbid")

    model: Literal["glm-4.6v-flash"] = VISION_MODEL
    messages: tuple[SystemMessage, UserMessage] = Field(repr=False)
    thinking: ThinkingOptions = Field(default_factory=ThinkingOptions)
    max_tokens: int = 4096
    stream: Literal[False] = False


class ProviderErrorDetails(BaseModel):
    """Only the numeric business code is accepted from an untrusted error body."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    code: str | None = Field(default=None, pattern=r"^[0-9]{1,10}$")


class ProviderErrorEnvelope(BaseModel):
    """An error body containing the sanitized business code."""

    error: ProviderErrorDetails


class PurchaseTextRequest(BaseModel):
    """Use only the selected free text model, with no tools or paid fallback."""

    model: Literal["glm-4.7-flash"] = "glm-4.7-flash"
    messages: tuple[SystemMessage, PurchaseTextMessage] = Field(repr=False)
    thinking: ThinkingOptions = Field(default_factory=ThinkingOptions)
    max_tokens: int = 4096
    stream: Literal[False] = False


class RecipeRequest(BaseModel):
    """A bounded recipe request to the retained free GLM text model."""

    model: Literal["glm-4.7-flash"] = "glm-4.7-flash"
    messages: tuple[SystemMessage, RecipeInputMessage] = Field(repr=False)
    thinking: ThinkingOptions = Field(default_factory=ThinkingOptions)
    max_tokens: int = 4096
    stream: Literal[False] = False

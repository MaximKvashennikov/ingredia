"""Provider-neutral message and completion envelopes."""

import base64
from typing import Literal

from pydantic import BaseModel, Field

from ingredia.recognition.media import PreparedPhoto


class TextPart(BaseModel):
    """A text component in a multimodal message."""

    type: Literal["text"] = "text"
    text: str


class ImageURL(BaseModel):
    """An inline image address excluded from diagnostic representations."""

    url: str = Field(repr=False)

    @classmethod
    def from_photo(cls, photo: PreparedPhoto) -> "ImageURL":
        """Encode normalized bytes without a Telegram URL or metadata."""
        encoded = base64.b64encode(photo.data).decode("ascii")
        return cls(url=f"data:{photo.media_type};base64,{encoded}")


class ImagePart(BaseModel):
    """An image component in a multimodal message."""

    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


class SystemMessage(BaseModel):
    """Trusted extraction instructions, excluded from diagnostics."""

    role: Literal["system"] = "system"
    content: str = Field(repr=False)


class UserMessage(BaseModel):
    """Untrusted photo input and accompanying extraction request."""

    role: Literal["user"] = "user"
    content: list[TextPart | ImagePart] = Field(repr=False)


class PurchaseTextMessage(BaseModel):
    """Untrusted purchase text with a bounded input size."""

    role: Literal["user"] = "user"
    content: str = Field(max_length=4000, repr=False)


class CompletionMessage(BaseModel):
    """Provider output text kept out of representations."""

    content: str = Field(max_length=50_000, repr=False)


class CompletionChoice(BaseModel):
    """A single generation with an explicit completion status."""

    message: CompletionMessage
    finish_reason: str


class VisionCompletion(BaseModel):
    """A single non-streaming completion; domain validation follows separately."""

    choices: list[CompletionChoice] = Field(min_length=1, max_length=1, repr=False)


class RecipeInputMessage(BaseModel):
    """Bound the recipe stock context separately from purchase text."""

    role: Literal["user"] = "user"
    content: str = Field(max_length=24000, repr=False)

"""Convert a completed generation into validated domain observations."""

import re

from pydantic import BaseModel, ValidationError

from ingredia.adapters.chat_completions.models import VisionCompletion
from ingredia.logging_config import get_logger
from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.models import PhotoRecognition

JSON_FENCE = re.compile(r"\x60\x60\x60(?:json)?\s*\n(.*?)\n\x60\x60\x60", re.DOTALL)


def parse_model[T: BaseModel](completion: VisionCompletion, model: type[T]) -> T:
    """Reject truncated or schema-invalid results without exposing their contents."""
    choice = completion.choices[0]
    if choice.finish_reason != "stop":
        raise RecognitionFailure(FailureCode.INVALID_RESPONSE)
    text = choice.message.content.strip()
    fenced = JSON_FENCE.fullmatch(text)
    content = fenced.group(1) if fenced is not None else text
    try:
        return model.model_validate_json(content)
    except ValidationError as error:
        get_logger(__name__).warning(
            "AI output failed validation: schema=%s error_types=%s",
            model.__name__,
            sorted({item["type"] for item in error.errors()}),
        )
        raise RecognitionFailure(FailureCode.INVALID_RESPONSE) from None


def parse_observations(completion: VisionCompletion) -> PhotoRecognition:
    """Validate extraction through the same safe completion parser."""
    return parse_model(completion, PhotoRecognition)

"""Map Groq failures to safe categories and log bounded diagnostic codes."""

from pydantic import BaseModel, Field, ValidationError

from ingredia.logging_config import get_logger
from ingredia.recognition.errors import FailureCode, RecognitionFailure


class ErrorDetails(BaseModel):
    """Accept only a bounded code, never error text or failed generations."""

    code: str | None = Field(default=None, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class ErrorEnvelope(BaseModel):
    """Read only the safe subset of a provider error."""

    error: ErrorDetails


def provider_failure(status: int, body: bytes) -> RecognitionFailure:
    """Log status and an allowlisted code without user payloads or credentials."""
    diagnostic = None
    try:
        diagnostic = ErrorEnvelope.model_validate_json(body).error.code
    except ValidationError:
        pass
    statuses = {
        400: FailureCode.MODEL_UNAVAILABLE,
        401: FailureCode.CREDENTIALS,
        402: FailureCode.BILLING,
        403: FailureCode.CREDENTIALS,
        404: FailureCode.MODEL_UNAVAILABLE,
        413: FailureCode.INVALID_IMAGE,
        422: FailureCode.INVALID_RESPONSE,
        429: FailureCode.QUOTA,
        503: FailureCode.PROVIDER_BUSY,
    }
    allowed_codes = {
        "json_validate_failed",
        "rate_limit_exceeded",
        "invalid_api_key",
        "model_not_found",
        "permission_denied",
        "context_length_exceeded",
        "invalid_request_error",
        "invalid_image",
    }
    diagnostic = diagnostic if diagnostic in allowed_codes else "other"
    category = statuses.get(status, FailureCode.UNAVAILABLE)
    if diagnostic == "json_validate_failed":
        category = FailureCode.INVALID_RESPONSE
    get_logger(__name__).warning(
        "Groq request rejected: http_status=%d category=%s code=%s",
        status,
        category.value,
        diagnostic,
    )
    return RecognitionFailure(category)

"""Typed, transport-independent failures without secret payloads."""

from enum import StrEnum


class FailureCode(StrEnum):
    """Stable machine-readable reasons shared by application adapters."""

    FORBIDDEN = "forbidden"
    DUPLICATE = "duplicate"
    BUSY = "busy"
    COOLDOWN = "cooldown"
    INVALID_IMAGE = "invalid_image"
    TIMEOUT = "timeout"
    PROVIDER_BUSY = "provider_busy"
    BILLING = "billing"
    UNAVAILABLE = "unavailable"
    CREDENTIALS = "credentials"
    QUOTA = "quota"
    INVALID_RESPONSE = "invalid_response"
    MODEL_UNAVAILABLE = "model_unavailable"


class RecognitionFailure(Exception):
    """A safe failure with no provider response body or credentials."""

    def __init__(self, code: FailureCode, provider_code: str | None = None) -> None:
        """Store a typed reason and an optional sanitized provider code."""
        self.code = code
        self.provider_code = provider_code
        super().__init__(code.value)

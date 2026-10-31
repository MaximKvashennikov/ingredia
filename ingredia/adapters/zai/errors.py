"""Declarative conversion of Z.ai failures to application error codes."""

from pydantic import TypeAdapter, ValidationError

from ingredia.adapters.zai.models import ProviderErrorDetails, ProviderErrorEnvelope
from ingredia.recognition.errors import FailureCode, RecognitionFailure

BUSINESS_FAILURES = {
    "1305": FailureCode.PROVIDER_BUSY,
    "1113": FailureCode.BILLING,
}
STATUS_FAILURES = {
    400: FailureCode.MODEL_UNAVAILABLE,
    401: FailureCode.CREDENTIALS,
    403: FailureCode.CREDENTIALS,
    404: FailureCode.MODEL_UNAVAILABLE,
    422: FailureCode.MODEL_UNAVAILABLE,
    429: FailureCode.QUOTA,
}
ERROR_SCHEMA: TypeAdapter[ProviderErrorEnvelope | ProviderErrorDetails] = TypeAdapter(
    ProviderErrorEnvelope | ProviderErrorDetails
)


def _business_code(body: bytes) -> str | None:
    try:
        error = ERROR_SCHEMA.validate_json(body)
    except ValidationError:
        return None
    if isinstance(error, ProviderErrorEnvelope):
        return error.error.code
    return error.code


def provider_failure(status: int, body: bytes) -> RecognitionFailure:
    """Select a safe category without forwarding provider text or credentials."""
    code = _business_code(body)
    default = STATUS_FAILURES.get(status, FailureCode.UNAVAILABLE)
    return RecognitionFailure(BUSINESS_FAILURES.get(code or "", default), code)

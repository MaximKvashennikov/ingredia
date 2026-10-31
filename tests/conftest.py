"""Synthetic, non-personal recognition fixtures."""

from io import BytesIO

import pytest
from PIL import Image

from ingredia.recognition.models import PhotoRecognition


@pytest.fixture
def jpeg() -> bytes:
    """Return a small image containing no real products or personal metadata."""
    image = Image.new("RGB", (32, 24), "white")
    target = BytesIO()
    image.save(target, format="JPEG")
    return target.getvalue()


@pytest.fixture
def recognition() -> PhotoRecognition:
    """Return expected observations for an artificial provider response."""
    return PhotoRecognition.model_validate(
        {
            "products": [
                {
                    "name": "Молоко",
                    "visual_description": "Белый пакет с читаемой надписью молоко",
                    "brand": None,
                    "package_count": 2,
                    "quantity_per_package": {"value": 1, "unit": "l", "evidence": "На пакете: 1 л"},
                    "expiry_date": None,
                    "expiry_evidence": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                }
            ],
            "warnings": ["Срок на фотографии не читается"],
        }
    )

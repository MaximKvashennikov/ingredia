"""Fixed provider route and bounds for the authorized vision trial."""

from typing import Final, Literal

from ingredia.adapters.chat_completions.client import MAX_RESPONSE_BYTES as MAX_RESPONSE_BYTES

VISION_MODEL: Final[Literal["glm-4.6v-flash"]] = "glm-4.6v-flash"
ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"
PROMPT_VERSION = "food-photo-v1"

"""Run the Telegram photo trial with centrally configured logging."""

import uvicorn

from ingredia.logging_config import configure_logging
from ingredia.settings import get_settings


def main() -> None:
    """Configure logging once and start one local process without reload."""
    config = get_settings()
    secrets = tuple(
        secret
        for secret in (
            config.telegram.user.token,
            config.telegram.admin.token,
            config.ai.zai.api_key,
            config.ai.groq.api_key,
            config.database.url,
        )
        if secret is not None
    )
    configure_logging(config.logging.level, secrets)
    uvicorn.run(
        "ingredia.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        log_config=None,
    )


if __name__ == "__main__":
    main()

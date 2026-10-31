FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.1 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY ingredia ./ingredia
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --create-home appuser
USER appuser
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["/app/.venv/bin/python", "-m", "ingredia"]

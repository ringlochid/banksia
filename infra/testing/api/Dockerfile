FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY README.md /app/README.md
COPY pyproject.toml /app/pyproject.toml
COPY apps/api/src /app/apps/api/src
COPY apps/api/tests /app/apps/api/tests
COPY docs-internal/design/appendices/workflow-seeds /app/docs-internal/design/appendices/workflow-seeds
COPY scripts/testing /app/scripts/testing

RUN python -m pip install --upgrade pip \
    && pip install "/app[postgres,dev]"

CMD ["banksia", "--help"]

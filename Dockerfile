FROM python:3.11-slim AS base

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ src/
RUN pip install -e ".[ml]"

# --- runtime image -----------------------------------------------------------
FROM base AS runtime
COPY pipelines/ pipelines/
COPY configs/ configs/
EXPOSE 8000
CMD ["uvicorn", "predictormaster.serving.api:build_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]

# One-command deck image: build the UI, then serve UI + API on port 8077.
# Usage:  docker compose up        (from the ict_trader/ directory)

# --- stage 1: build the React deck ---
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- stage 2: python runtime serving API + the built UI ---
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ICT_TRADER_API_HOST=0.0.0.0 \
    ICT_TRADER_STATIC_DIR=/app/frontend/dist \
    ICT_TRADER_DB_URL=sqlite+aiosqlite:////app/data/ict_trader.db

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY configs ./configs
RUN pip install --upgrade pip && pip install ".[serve]"
COPY --from=ui /ui/dist ./frontend/dist
RUN mkdir -p /app/data

EXPOSE 8077
# run_all builds nothing (UI already built) and seeds sample data if the store is empty.
CMD ["python", "scripts/run_all.py", "--no-build"]

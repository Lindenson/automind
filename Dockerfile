# Multi-stage: build frontend, then run backend serving the built SPA.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist
# config/*.yaml and the Alembic migrations ship with the backend sources.
ENV CONFIG_DIR=/app/backend/config
EXPOSE 8000
# Bring the schema to head (Alembic), then serve. The API also checks migrations at startup.
CMD ["sh", "-c", "uv run --no-sync python -m automind.infrastructure.db.migrate && exec uv run --no-sync uvicorn automind.api.app:app --host 0.0.0.0 --port 8000"]

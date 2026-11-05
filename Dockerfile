# AutoMind image: build the frontend, then run the backend API that also serves the built SPA.
# Built and started by scripts/deploy.sh (docker compose). Secrets come from .env at run time, never baked in.
# Stage `check` (scripts/check.sh --docker) holds the dev dependencies and the tests; the default (last) stage is
# the runtime image and contains neither.

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- quality gates in Docker: ruff, mypy, import-linter, pytest, frontend typecheck + vitest -----------------------
FROM python:3.13-slim AS check
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-install-project
WORKDIR /app/frontend
COPY --from=web /web/node_modules ./node_modules
WORKDIR /app
COPY scripts/ ./scripts/
COPY deploy/ ./deploy/
COPY frontend/ ./frontend/
COPY backend/ ./backend/
RUN cd backend && uv sync --frozen
ENV PATH=/app/backend/.venv/bin:$PATH \
    CONFIG_DIR=/app/backend/config \
    HOME=/tmp
CMD ["scripts/check.sh"]

# --- runtime --------------------------------------------------------------------------------------------------------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1
WORKDIR /app/backend
# dependencies first (cached layer), then the project itself (without the tests)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --exclude=tests backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/frontend/dist
ENV PATH=/app/backend/.venv/bin:$PATH \
    FRONTEND_DIST=/app/frontend/dist \
    CONFIG_DIR=/app/backend/config
RUN useradd --system --uid 10001 --home /app automind && chown -R automind /app
USER automind
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
# Bring the schema to head (Alembic), then serve.
CMD ["sh", "-c", "python -m automind.infrastructure.db.migrate && exec uvicorn automind.api.app:app --host 0.0.0.0 --port 8000 --proxy-headers --workers 1"]

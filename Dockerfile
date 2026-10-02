# syntax=docker/dockerfile:1
FROM node:22.23.3-bookworm-slim AS frontend
WORKDIR /build
COPY vehicle_web_view/frontend/package.json vehicle_web_view/frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY vehicle_web_view/frontend/index.html vehicle_web_view/frontend/vite.config.js ./
COPY vehicle_web_view/frontend/src ./src
RUN npm test && npm run build

FROM ghcr.io/astral-sh/uv:0.12.12 AS uv

FROM ubuntu:24.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev build-essential git ca-certificates \
    libgl1 libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app/vehicle_web_view/backend
COPY vehicle_web_view/backend/pyproject.toml vehicle_web_view/backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra gpu --no-dev --no-install-project --python /usr/bin/python3.12
COPY vehicle_web_view/backend/src ./src
COPY vehicle_web_view/backend/scripts ./scripts
COPY vehicle_web_view/backend/config.yaml vehicle_web_view/backend/runtime_config.yaml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra gpu --no-dev --no-editable --python /usr/bin/python3.12
COPY --from=frontend /build/dist /app/vehicle_web_view/frontend/dist
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin perception
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/cache \
    HF_HOME=/tmp/huggingface \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor \
    TRITON_CACHE_DIR=/tmp/triton \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
USER 10001:10001
CMD ["python", "scripts/server/extract_run_server.py"]

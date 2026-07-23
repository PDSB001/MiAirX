# ──── Stage 1: Build wheel ────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps
RUN pip install --no-cache-dir build

COPY pyproject.toml README.md .
COPY src/ src/

# Build wheel
RUN python -m build --wheel

# ──── Stage 2: Runtime ────
FROM python:3.12-slim

WORKDIR /app

# System audio deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy and install pre-built wheel
COPY --from=builder /build/dist /tmp/dist
RUN pip install --no-cache-dir /tmp/dist/*.whl && rm -rf /tmp/dist

# Volume for persistent config
RUN mkdir -p /app/conf
VOLUME ["/app/conf"]

EXPOSE 8200 8300

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8300/api/status')" || exit 1

CMD ["python", "-m", "miairx"]

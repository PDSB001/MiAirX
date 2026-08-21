FROM node:24-alpine AS frontend-builder

WORKDIR /build/frontend
RUN npm install --global pnpm@11.19.0

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build


FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml README.md .
COPY src/ src/
COPY --from=frontend-builder /build/src/miairx/web/static/app/ src/miairx/web/static/app/
RUN pip install --no-cache-dir .

# Config volume
RUN mkdir -p /app/conf
VOLUME ["/app/conf"]

EXPOSE 8200/tcp 8300/tcp 1900/udp 5353/udp 7000-7099/tcp

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/health')" || exit 1

CMD ["python", "-m", "miairx"]

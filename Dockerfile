FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml README.md .
COPY src/ src/
RUN pip install --no-cache-dir .

# Config volume
RUN mkdir -p /app/conf
VOLUME ["/app/conf"]

EXPOSE 8200 8300

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8300/api/status')" || exit 1

CMD ["python", "-m", "miairx"]

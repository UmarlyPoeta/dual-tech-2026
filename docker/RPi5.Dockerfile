# =============================================================================
# RPi5.Dockerfile — Dual Tech 2026 (ARM64)
# Multi-stage build for Raspberry Pi 5 running Debian Bookworm
#
# Build:
#   docker build -f docker/RPi5.Dockerfile -t dualtech:latest .
#
# Run:
#   docker run --privileged --network host \
#     -v /dev:/dev -v $(pwd)/config:/app/config \
#     -v $(pwd)/models:/app/models -v $(pwd)/logs:/app/logs \
#     -e PLATFORM=ugv dualtech:latest
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — compile wheels for native extensions
# ---------------------------------------------------------------------------
FROM python:3.11-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config swig \
    libcap-dev libjpeg-dev libopenjp2-7-dev \
    libzbar-dev libssl-dev libffi-dev \
    libatlas-base-dev libgpiod-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime — slim image with only what we need
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 libjpeg62-turbo libopenjp2-7 \
    libatlas3-base libgpiod2 pigpio \
    v4l-utils i2c-tools curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

COPY . .

RUN mkdir -p /app/logs /app/models /app/config

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PLATFORM=ugv

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8080/api/health || exit 1

ENTRYPOINT ["python3"]
CMD ["-c", "import os, subprocess, sys; sys.exit(subprocess.call([sys.executable, f'main_{os.environ.get(\"PLATFORM\", \"ugv\")}.py']))"]

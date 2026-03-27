# =============================================================================
# RPi5.Dockerfile — Dual Tech 2026 (ARM64)
# Single-stage build for Raspberry Pi 5 running Debian Bookworm
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
# Single-stage runtime image (more stable on resource-constrained Pi builds)
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libzbar0 libjpeg62-turbo libopenjp2-7 \
        libatlas3-base libgpiod2 \
        python3-opencv \
        curl; \
    if apt-cache show libopenblas0-pthread >/dev/null 2>&1; then \
        apt-get install -y --no-install-recommends libopenblas0-pthread; \
    elif apt-cache show libopenblas0 >/dev/null 2>&1; then \
        apt-get install -y --no-install-recommends libopenblas0; \
    fi; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-docker.txt requirements-ml.txt ./

ARG INSTALL_ML=auto
RUN PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple \
    pip install --no-cache-dir --prefer-binary -r requirements-docker.txt && \
    if [ "$INSTALL_ML" = "0" ] || { [ "$INSTALL_ML" = "auto" ] && [ "$(dpkg --print-architecture)" = "armhf" ]; }; then \
        echo "Skipping ML deps (ultralytics/torch) for this architecture"; \
    else \
        PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple \
        pip install --no-cache-dir --prefer-binary -r requirements-ml.txt; \
    fi

COPY . .

RUN mkdir -p /app/logs /app/models /app/config

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PLATFORM=ugv

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8080/api/health || exit 1

ENTRYPOINT ["python3"]
CMD ["-c", "import os, subprocess, sys; sys.exit(subprocess.call([sys.executable, f'main_{os.environ.get(\"PLATFORM\", \"ugv\")}.py']))"]

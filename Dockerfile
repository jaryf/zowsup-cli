# ============================================================
# Zowsup Dashboard — Backend Dockerfile
# ============================================================
# Multi-stage build: builder installs deps, final image is lean.
#
# Build:
#   docker build -f Dockerfile -t zowsup-dashboard .
#
# Run:
#   docker run -p 5000:5000 \
#     -e DASHBOARD_API_TOKEN=your-token \
#     -v $(pwd)/data:/app/data \
#     -v $(pwd)/conf:/app/conf \
#     zowsup-dashboard

# ── Stage 1: builder ────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools (needed for some C-extension wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/       app/
COPY conf/      conf/
COPY proto/     proto/
COPY script/    script/

# Create runtime directories
RUN mkdir -p data logs

# Non-root user for security
RUN groupadd -r dashboard && useradd -r -g dashboard dashboard \
 && chown -R dashboard:dashboard /app
USER dashboard

# Expose the API port
EXPOSE 5000

# Health check — polls /api/health every 30 s
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')"

# Default environment (override at runtime)
ENV DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=5000 \
    DASHBOARD_DEBUG=false \
    LOG_LEVEL=INFO

ENTRYPOINT ["python", "script/dashboard.py"]

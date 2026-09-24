# syntax=docker/dockerfile:1.27

# ─── Stage 1: dependency builder ─────────────────────────────────────────────
# Digest from `skopeo inspect --format '{{.Digest}}' docker://docker.io/library/python:3.14-alpine` (multi-arch index digest); Renovate's pinDigests rule keeps it current.
FROM python:3.14-alpine@sha256:9e9fde4d32eedce0b661d9ab91e826b62dddf28e928c230ec55f1866cac66b01 AS builder

WORKDIR /build

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    postgresql-dev

# uv from its official image, pinned. Keep it in step with the uv pin in
# .github/workflows/*.yml.
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

# Runtime dependencies only, exactly as locked. Build the venv at /venv so the
# shebangs are correct in the final image. The app itself is copied, not installed.
RUN UV_PROJECT_ENVIRONMENT=/venv UV_PYTHON_DOWNLOADS=never uv sync --frozen --no-dev --no-install-project --no-cache

# ─── Stage 2: production image ────────────────────────────────────────────────
# Same digest and provenance as the builder stage above.
FROM python:3.14-alpine@sha256:9e9fde4d32eedce0b661d9ab91e826b62dddf28e928c230ec55f1866cac66b01 AS final

WORKDIR /app

# Runtime dependencies only
RUN apk add --no-cache \
    libpq \
    libffi

# Non-root user for security, uid/gid 1000 to match the Helm chart's
# securityContext (runAsUser/fsGroup: 1000).
RUN addgroup -S -g 1000 openwhistle && adduser -S -u 1000 -G openwhistle openwhistle

# Copy virtualenv from builder — shebangs point to /venv (same path)
COPY --from=builder /venv /venv

# Copy application code
COPY --chown=openwhistle:openwhistle . .

# Self-hosted fonts (Sora + JetBrains Mono, OFL), committed once in docs/fonts
# and shared with the public site — no download at build time.
COPY --chown=openwhistle:openwhistle docs/fonts/*.woff2 /app/app/static/fonts/

# Generate the file-integrity manifest over the exact shipped bytes (after fonts
# are in place). -B avoids writing .pyc during the walk (PYTHONDONTWRITEBYTECODE
# is set later); the script imports no settings, so no SECRET_KEY is needed.
RUN /venv/bin/python -B scripts/generate_integrity_manifest.py

USER openwhistle

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=4009

EXPOSE 4009

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:4009/health', timeout=5).status != 200)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4009", "--no-access-log"]

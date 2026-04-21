# syntax=docker/dockerfile:1.10

# ─── Stage 1: dependency builder ─────────────────────────────────────────────
FROM python:3.14-alpine AS builder

WORKDIR /build

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    postgresql-dev \
    curl \
    unzip

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.6.0

COPY pyproject.toml README.md ./

# Build venv at /venv so shebangs are correct in the final image
RUN uv venv /venv && \
    . /venv/bin/activate && \
    uv pip install --no-cache ".[dev]"

# Download and bundle self-hosted fonts
RUN mkdir -p /build/fonts && \
    # JetBrains Mono (OFL License)
    curl -L "https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip" \
         -o /tmp/jbmono.zip && \
    unzip -j /tmp/jbmono.zip "fonts/webfonts/*.woff2" -d /build/fonts/ && \
    # Spectral (OFL License)
    curl -L "https://cdn.jsdelivr.net/npm/@fontsource/spectral@5.1.1/files/spectral-latin-400-normal.woff2" \
         -o /build/fonts/spectral-latin-400-normal.woff2 && \
    curl -L "https://cdn.jsdelivr.net/npm/@fontsource/spectral@5.1.1/files/spectral-latin-600-normal.woff2" \
         -o /build/fonts/spectral-latin-600-normal.woff2 && \
    curl -L "https://cdn.jsdelivr.net/npm/@fontsource/spectral@5.1.1/files/spectral-latin-400-italic.woff2" \
         -o /build/fonts/spectral-latin-400-italic.woff2 && \
    # Source Serif 4 (OFL License)
    curl -L "https://cdn.jsdelivr.net/npm/@fontsource/source-serif-4@5.1.1/files/source-serif-4-latin-400-normal.woff2" \
         -o /build/fonts/source-serif-4-latin-400-normal.woff2 && \
    curl -L "https://cdn.jsdelivr.net/npm/@fontsource/source-serif-4@5.1.1/files/source-serif-4-latin-700-normal.woff2" \
         -o /build/fonts/source-serif-4-latin-700-normal.woff2 && \
    rm -f /tmp/jbmono.zip

# ─── Stage 2: production image ────────────────────────────────────────────────
FROM python:3.14-alpine AS final

WORKDIR /app

# Runtime dependencies only
RUN apk add --no-cache \
    libpq \
    libffi \
    curl

# Non-root user for security
RUN addgroup -S openwhistle && adduser -S openwhistle -G openwhistle

# Copy virtualenv from builder — shebangs point to /venv (same path)
COPY --from=builder /venv /venv

# Copy fonts from builder
COPY --from=builder /build/fonts /app/app/static/fonts/

# Copy application code
COPY --chown=openwhistle:openwhistle . .

RUN chown -R openwhistle:openwhistle /app/app/static/fonts/

USER openwhistle

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=4009

EXPOSE 4009

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:4009/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4009", "--no-access-log"]

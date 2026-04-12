# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files first (cache layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# Copy source
COPY . .

# --- Stage 2: Production ---
FROM python:3.12-slim AS production

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 wget && \
    rm -rf /var/lib/apt/lists/*

# Security: non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /app/src ./src
COPY --from=builder /app/alembic.ini ./
COPY --from=builder /app/pyproject.toml ./

# Switch to non-root
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 -O /dev/null http://localhost:8000/api/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

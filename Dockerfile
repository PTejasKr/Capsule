# =====================================================================
# Stage 1: Build dependency wheelhouse
# =====================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Install compilation tools if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .

# Build wheels to cache dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# =====================================================================
# Stage 2: Runtime Environment
# =====================================================================
FROM python:3.12-slim AS runner

WORKDIR /app

# Create non-privileged system user for process isolation
RUN groupadd -g 10001 capsule && \
    useradd -m -u 10001 -g capsule -s /sbin/nologin -c "capsule system user" capsule

# Copy installed Python packages from builder
COPY --from=builder --chown=capsule:capsule /root/.local /home/capsule/.local
ENV PATH=/home/capsule/.local/bin:$PATH

# Copy backend files
COPY backend /app/backend
COPY brd /app/brd

# Create data directory for SQLite persistence and set permissions
RUN mkdir -p /app/data && chown -R capsule:capsule /app

# Switch to isolated user context
USER capsule

EXPOSE 8000

# Healthcheck to verify FastAPI service status
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

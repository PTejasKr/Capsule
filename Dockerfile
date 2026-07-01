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

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

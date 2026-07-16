# Multi-stage Build Stage
FROM python:3.12-alpine AS builder

WORKDIR /app

# Install compiler and headers for dependencies
RUN apk add --no-cache gcc musl-dev libffi-dev cargo openssl-dev

# Setup virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency definition and install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Run Stage
FROM python:3.12-alpine

WORKDIR /app

# Install runtime dependencies if needed
RUN apk add --no-cache libffi openssl

# Copy virtualenv and app files
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY app/ ./app/

# Create directory for SQLite database storage
RUN mkdir -p /app/data

EXPOSE 8000

# Run alembic migrations on startup, then start Uvicorn server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

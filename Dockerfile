# Multi-stage build for optimized production image
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only (no gcc, build tools)
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local

# Set PATH to use locally installed packages
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/docs', timeout=5)" || exit 1

# Expose port
EXPOSE 8000

# Start application
# NOTE: All sensitive environment variables (JWT_SECRET, STRIPE_*_KEY, TWILIO_AUTH_TOKEN, etc.)
# must be provided at runtime via:
# - docker run -e VARIABLE_NAME=value
# - docker-compose environment variables
# - Kubernetes secrets mounted as env vars
# - Platform-specific secret management (Railway, Render, etc.)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# =============================================================================
# Backend-only container image
# =============================================================================
# Frontend is deployed separately via Azure Static Web Apps.

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libicu-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Bicep standalone CLI for Bicep → ARM template compilation
RUN curl -Lo /usr/local/bin/bicep \
        https://github.com/Azure/bicep/releases/latest/download/bicep-linux-x64 \
    && chmod +x /usr/local/bin/bicep \
    && bicep --version

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY backend/app ./app

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

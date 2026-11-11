FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary directly from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PYTHONPATH=/app/backend/src

# Copy project configuration for layer caching
COPY backend/pyproject.toml backend/uv.lock* ./backend/

# Install dependencies using uv into virtual environment
RUN cd backend && uv sync --frozen --no-install-project

# Copy application source code
COPY backend ./backend
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Final sync to install project package
RUN cd backend && uv sync --frozen

EXPOSE 8000

# Start Supervisor to run both Uvicorn and Taskiq in one container
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

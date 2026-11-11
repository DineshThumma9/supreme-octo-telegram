FROM python:3.12-slim

# Copy uv binary directly from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Optimize python and uv environment
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PYTHONPATH=/app/src

# Copy dependency manifests first for Docker layer caching
COPY pyproject.toml uv.lock* ./

# Install dependencies into virtualenv without project code
RUN uv sync --frozen --no-install-project

# Copy application code
COPY . .

# Complete project installation
RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

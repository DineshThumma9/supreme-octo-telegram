FROM python-3.12:alphine 

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app 


ENV UV_COMPILE_BYTECODE=1 
ENV UV_LINK_MODE=copy 

COPY pyproject.toml uvlock* ./
RUN uv sync --frozen --no-install-project

COPY . . 


RUN uv sync --frozen 

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.main:app", "--port", "8000"]

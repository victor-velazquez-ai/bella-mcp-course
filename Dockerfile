# Bella as a remote MCP server (Streamable HTTP). Works on Render, Railway, Fly.io,
# Azure Container Apps, AWS App Runner, Cloud Run...
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BELLA_HOME=/app BELLA_HOST=0.0.0.0 BELLA_PORT=8000

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && python -c "from bella_mcp.config import Settings; from bella_mcp.seed import build_database; build_database(Settings().db_path)"

# Never run as root
RUN useradd --create-home bella && mkdir -p /app/logs && chown -R bella /app
USER bella

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", os.environ[\"BELLA_PORT\"])}/health')"
CMD ["python", "-m", "bella_mcp", "http"]

# The kit maker as a remote MCP server (for chat apps: Gemini, Claude.ai, ChatGPT). Put it behind HTTPS.
#   docker build -t virada-kit . && docker run -p 8000:8000 -e VIRADA_KIT_PUBLIC_URL=https://your.host virada-kit
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache .
RUN useradd -m app && mkdir -p /work && chown app /work
USER app
ENV VIRADA_KIT_WORKDIR=/work
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["virada-kit", "--http", "--host", "0.0.0.0", "--port", "8000"]

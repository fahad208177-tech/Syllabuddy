# Syllabuddy MCP server (Streamable HTTP on :8765/mcp)
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY syllabus_core ./syllabus_core
COPY mcp_server ./mcp_server
COPY data/syllabus.json data/embeddings-*.npz ./data/
ENV SYLLABUDDY_HOST=0.0.0.0 SYLLABUDDY_PORT=8765 PYTHONUNBUFFERED=1
# Download the embedding model at build time so cold starts stay fast.
RUN python -c "from syllabus_core.service import SyllabusService; SyllabusService()"
EXPOSE 8765
CMD ["python", "-m", "mcp_server"]

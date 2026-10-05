# Syllabuddy: the voice web app and the public MCP server (with OAuth account
# linking) on one port. Works as a Hugging Face Docker Space as-is, and on any
# host that runs a container and gives it a public HTTPS address.
#
#   docker build -t syllabuddy .
#   docker run -p 7860:7860 -e SYLLABUDDY_PUBLIC_URL=https://your.host syllabuddy
FROM python:3.12-slim

# Spaces runs containers as uid 1000; own the app directory so the cache and model can be written.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    PORT=7860 SYLLABUDDY_DB=/tmp/syllabuddy.db
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user syllabus_core ./syllabus_core
COPY --chown=user mcp_server ./mcp_server
COPY --chown=user assistant ./assistant
COPY --chown=user deploy ./deploy
COPY --chown=user alexa-addon/media ./alexa-addon/media
COPY --chown=user data/*.json data/embeddings-*.npz ./data/

# Download the embedding model and load every syllabus at build time, so a cold start answers in seconds.
RUN python -c "from syllabus_core.service import SyllabusService; s = SyllabusService(); print(len(s.objectives), 'objectives')"

EXPOSE 7860
CMD ["python", "-m", "deploy.serve"]

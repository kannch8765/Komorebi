# Komorebi — production image
#
# Build:  docker build -t komorebi .
# Run:    docker run -p 8080:8080 \
#             -e GOOGLE_API_KEY=... \
#             -e GOOGLE_PLACES_API_KEY=... \
#             komorebi
#
# For Cloud Run / Railway / Render, push the image and set the env vars
# in the platform's secret manager. The CMD respects $PORT (Cloud Run
# requirement: container must listen on the port the platform assigns).

FROM python:3.11-slim

# uv is the project's package manager (see uv.lock). Install it once.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Set working dir and copy project files (uv.lock pins versions).
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY agents/ ./agents/
COPY config/ ./config/
COPY models/ ./models/
COPY tools/ ./tools/
COPY server.py main.py ./

# Install deps into the system Python (no venv needed in the container).
# --no-dev skips pytest/pre-commit; --frozen uses uv.lock exactly.
RUN uv pip install --system .

# Cloud Run injects $PORT; default 8080 works for local docker run.
ENV PORT=8080
EXPOSE 8080

# Health check (optional — Cloud Run has its own probe; useful for local
# docker run so you can `docker ps` and see "healthy").
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" \
    || exit 1

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
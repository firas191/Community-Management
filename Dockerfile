# Single image shared by api, worker, and beat services. Slim, no ML toolchain
# in Week 1 so the build stays fast and always succeeds.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg[binary] ships its own libpq, so no system postgres-dev is needed.
# curl is used by the compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

# Then the source.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

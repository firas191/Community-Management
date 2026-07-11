# Single image shared by api, worker, and beat. From Week 3 it bundles the
# sentiment stack (CPU-only torch + transformers). The model WEIGHTS are not baked
# into the image; they download on first use into HF_HOME, which docker-compose
# mounts as a named volume so they download once and persist across restarts. This
# keeps the image around 2 GB and avoids a large-image commit on constrained hosts.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    TRANSFORMERS_VERBOSITY=error

WORKDIR /app

# psycopg[binary] ships its own libpq, so no system postgres-dev is needed.
# curl is used by the compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching. CPU-only torch is ~200 MB versus ~2 GB for
# the default CUDA build and is enough for this project (CPU inference). Installing
# it first means the `nlp` extra's `torch==2.5.1` requirement is already satisfied.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip \
    && pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -e ".[dev,nlp]"

# Then the source.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

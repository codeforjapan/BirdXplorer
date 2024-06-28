ARG PYTHON_VERSION_CODE=3.10

FROM python:${PYTHON_VERSION_CODE}-bookworm AS builder
ARG PYTHON_VERSION_CODE

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY birdxplorer_api/__init__.py ./birdxplorer_api/

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client-15 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*;

RUN pip install --no-cache-dir -e ".[prod]"

FROM python:${PYTHON_VERSION_CODE}-slim-bookworm AS runner
ARG PYTHON_VERSION_CODE

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*;

RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /app
USER app

COPY --from=builder /usr/local/lib/python${PYTHON_VERSION_CODE}/site-packages /usr/local/lib/python${PYTHON_VERSION_CODE}/site-packages
COPY --chown=app:app . ./

ENTRYPOINT ["python", "-m", "gunicorn", "birdxplorer_api.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0"]

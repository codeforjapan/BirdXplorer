ARG PYTHON_VERSION_CODE=3.10
ARG ENVIRONMENT="dev"
# ENVIRONMENT: dev or prod, refer to project.optional-dependencies in pyproject.toml

FROM python:${PYTHON_VERSION_CODE}-bookworm as builder
ARG PYTHON_VERSION_CODE
ARG ENVIRONMENT

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY birdxplorer_migration/__init__.py ./birdxplorer_migration/

RUN if [ "${ENVIRONMENT}" = "prod" ]; then \
    apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client-15 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*; \
    fi

RUN pip install --no-cache-dir -e ".[${ENVIRONMENT}]"

FROM python:${PYTHON_VERSION_CODE}-slim-bookworm as runner
ARG PYTHON_VERSION_CODE
ARG ENVIRONMENT

WORKDIR /app

RUN if [ "${ENVIRONMENT}" = "prod" ]; then \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*; \
    fi

RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /app
USER app

COPY --from=builder /usr/local/lib/python${PYTHON_VERSION_CODE}/site-packages /usr/local/lib/python${PYTHON_VERSION_CODE}/site-packages
COPY --chown=app:app . ./

ENTRYPOINT ["python", "birdxplorer_migration/scripts/migrate_all.py", "birdxplorer_migration/data/appv1/"]

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
COPY birdxplorer/__init__.py ./birdxplorer/
RUN pip install --no-cache-dir -e ".[${ENVIRONMENT}]"

FROM python:${PYTHON_VERSION_CODE}-slim-bookworm as runner
ARG PYTHON_VERSION_CODE

WORKDIR /app

RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /app
USER app

COPY --from=builder /usr/local/lib/python${PYTHON_VERSION_CODE}/site-packages /usr/local/lib/python${PYTHON_VERSION_CODE}/site-packages
COPY --chown=app:app . ./

ENTRYPOINT ["python", "-m", "uvicorn", "birdxplorer.main:app", "--host", "0.0.0.0"]

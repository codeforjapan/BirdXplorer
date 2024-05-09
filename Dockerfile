ARG ENVIRONMENT="dev"
# ENVIRONMENT: dev or prod, refer to project.optional-dependencies in pyproject.toml

FROM python:3.11-bookworm as builder

WORKDIR /app
ARG ENVIRONMENT
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUSERBASE=/app/__pypackages__

# 一旦flit_coreによるビルドを通すために毎回丸ごとコピーする。
# あとでビルドに必要な最小限のファイルを調べます。
COPY . .
RUN pip install --user --no-cache-dir -e ".[${ENVIRONMENT}]"

FROM python:3.11-slim-bookworm as runner

WORKDIR /app
ENV PYTHONUSERBASE=/app/__pypackages__

RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /app
USER app

COPY --from=builder /app/__pypackages__ /app/__pypackages__
COPY --chown=app:app . ./

ENTRYPOINT ["python", "-m", "uvicorn", "birdxplorer.main:app", "--host", "0.0.0.0"]

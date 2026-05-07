ARG ENVIRONMENT="prod"

# Use the official Python image from the Docker Hub
FROM python:3.10

# Set the working directory in the container
WORKDIR /app
COPY pyproject.toml ./
COPY src/birdxplorer_etl/__init__.py ./src/birdxplorer_etl/
COPY .env ./

RUN python -m pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[prod]

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 postgresql-client-15 sqlite3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . ./

# Set the entry point to run the Prefect flow
ENTRYPOINT ["python", "src/birdxplorer_etl/main.py"]
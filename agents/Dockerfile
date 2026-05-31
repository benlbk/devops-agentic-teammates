FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir poetry==1.8.3 && \
    poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --no-root --only main

COPY src/ ./src/

RUN poetry install --no-interaction --no-ansi --only main

# Extra runtime deps not yet pinned in poetry.lock
RUN pip install --no-cache-dir prometheus-fastapi-instrumentator==7.0.0 \
    "setuptools<70" \
    opentelemetry-sdk==1.27.0 \
    opentelemetry-api==1.27.0 \
    opentelemetry-exporter-otlp-proto-http==1.27.0 \
    opentelemetry-instrumentation-fastapi==0.48b0 \
    opentelemetry-instrumentation-httpx==0.48b0 \
    opentelemetry-instrumentation-botocore==0.48b0 \
    opentelemetry-instrumentation-logging==0.48b0

FROM python:3.12-slim AS runtime

RUN groupadd -r agent && useradd -r -g agent agent

WORKDIR /app

COPY --from=base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=base /usr/local/bin /usr/local/bin
COPY --from=base /app/src ./src
COPY config/ ./config/

USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

ENV PYTHONPATH=/app/src

ENTRYPOINT ["python", "-m", "uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]

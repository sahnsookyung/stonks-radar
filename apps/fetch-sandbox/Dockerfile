FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/fetch-sandbox/src

WORKDIR /app
RUN addgroup --system frw && adduser --system --ingroup frw frw
COPY apps/fetch-sandbox/pyproject.toml apps/fetch-sandbox/pyproject.toml
COPY apps/fetch-sandbox/src apps/fetch-sandbox/src
RUN python -m pip install --no-cache-dir --only-binary=:all: /app/apps/fetch-sandbox
COPY apps/fetch-sandbox apps/fetch-sandbox
USER frw
CMD ["python", "-m", "fetch_sandbox.server"]

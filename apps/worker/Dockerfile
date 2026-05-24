FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src:/app/apps/worker/src

WORKDIR /app
RUN addgroup --system frw && adduser --system --ingroup frw frw
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
COPY apps/web/public/public apps/web/public/public
RUN pip install --no-cache-dir /app/apps/api
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY packages packages
COPY seeds seeds
COPY scripts scripts
RUN mkdir -p /app/artifacts/snapshots /app/published-public \
    && cp -a /app/apps/web/public/public/. /app/published-public/ \
    && chown -R frw:frw /app/artifacts /app/published-public
USER frw
CMD ["python", "-m", "frw_worker.main"]

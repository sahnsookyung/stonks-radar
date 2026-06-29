FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src

WORKDIR /app
RUN addgroup --system frw && adduser --system --ingroup frw frw \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
COPY apps/web/public/public apps/web/public/public
RUN python -m pip install --no-cache-dir --no-compile --only-binary=:all: /app/apps/api \
    && find /usr/local/lib/python3.12/site-packages \
      \( -type d -name tests -o -type d -name __pycache__ \) \
      -prune -exec rm -rf {} +
COPY apps/api apps/api
COPY packages packages
COPY seeds seeds
COPY scripts scripts
RUN mkdir -p /app/artifacts/snapshots /app/published-public \
    && cp -a /app/apps/web/public/public/. /app/published-public/ \
    && chown -R frw:frw /app/artifacts /app/published-public
COPY apps/api/docker-entrypoint.sh /usr/local/bin/frw-entrypoint
RUN chmod +x /usr/local/bin/frw-entrypoint
EXPOSE 8000
ENTRYPOINT ["frw-entrypoint"]
CMD ["sh", "-c", "cd /app/apps/api && alembic upgrade head && python /app/scripts/seed_database.py && uvicorn frw_api.main:app --host 0.0.0.0 --port 8000"]

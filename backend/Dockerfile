FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
RUN DJANGO_DEBUG=true python manage.py collectstatic --noinput

EXPOSE 8000
# Migrations run at start so that `docker compose up` on a fresh machine is enough.
# Threaded workers: an assistant request waits 10-60 s on the LLM, and must not hold a whole
# worker while other requests queue behind it. The metrics of the workers are gathered in
# PROMETHEUS_MULTIPROC_DIR (apps/core/metrics.py), emptied at every start.
CMD ["sh", "-c", "python manage.py migrate --noinput && if [ -n \"$PROMETHEUS_MULTIPROC_DIR\" ]; then rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\"; fi && gunicorn config.wsgi:application --config gunicorn.conf.py --bind 0.0.0.0:8000 --workers 2 --worker-class gthread --threads 4 --timeout 300"]

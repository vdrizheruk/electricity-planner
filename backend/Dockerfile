# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# WeasyPrint (PDF export): pango, the HarfBuzz subsetter and a font with Cyrillic and the
# hryvnia sign.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core shared-mime-info \
    && apt-get clean

FROM base AS builder
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM base AS runtime
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    XDG_CACHE_HOME=/tmp/.cache
WORKDIR /app
COPY . .
# Static files for WhiteNoise. The values below exist only for this build step.
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput \
    && chmod +x docker-entrypoint.sh
# Non-root: any numeric uid works on Kubernetes with runAsNonRoot.
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# WEB_CONCURRENCY sets the number of workers (read by gunicorn itself).
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--timeout", "120", \
     "--worker-tmp-dir", "/dev/shm", "--no-control-socket", "--access-logfile", "-", "--error-logfile", "-"]

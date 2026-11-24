#!/bin/sh
# Optional one-shot tasks before the server starts. In Kubernetes run them as a Job instead
# (RUN_MIGRATIONS=0) so that replicas do not race on migrations.
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
fi
if [ "${SEED_CATALOG:-0}" = "1" ]; then
    python manage.py seed_catalog
fi
exec "$@"

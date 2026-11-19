#!/bin/sh
# Container entrypoint.
#   web (default)  run database migrations, then serve with gunicorn
#   anything else  run it as a command, e.g. `manage.py createsuperuser`
set -eu

if [ "${1:-web}" = "web" ]; then
  if [ "${LEASEKEEP_MIGRATE_ON_START:-1}" = "1" ]; then
    python manage.py migrate --noinput
  fi
  exec gunicorn leasekeep.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    --access-logfile - \
    --error-logfile -
fi

if [ "$1" = "manage.py" ]; then
  shift
  exec python manage.py "$@"
fi
exec "$@"

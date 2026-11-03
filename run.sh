#!/usr/bin/env bash
# Start Miday for the local network: http://<this machine's IP>:8000
set -euo pipefail
cd "$(dirname "$0")"

# Virtualenv + dependencies (reinstalled only when requirements.txt changes).
# Django 5.2 needs Python 3.10 or newer; set PYTHON to pick a specific one.
if [ ! -x .venv/bin/python ]; then
  if [ -z "${PYTHON:-}" ]; then
    for version in 3.13 3.12 3.11 3.10; do
      if command -v "python$version" >/dev/null 2>&1; then PYTHON="python$version"; break; fi
    done
  fi
  PYTHON="${PYTHON:-python3}"
  "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || { echo "Miday needs Python 3.10 or newer; set PYTHON=/path/to/python3.x" >&2; exit 1; }
  "$PYTHON" -m venv .venv
fi
if [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install -q -r requirements.txt
  touch .venv/.installed
fi

# First run: create .env with a fresh secret key.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "DJANGO_SECRET_KEY=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(50))')" >> .env
  echo "Created .env"
fi
set -a; . ./.env; set +a

export PORT="${PORT:-8000}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-false}"
if [ -z "${PUBLIC_BASE_URL:-}" ]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  export PUBLIC_BASE_URL="http://${IP:-127.0.0.1}:$PORT"
fi

.venv/bin/python manage.py migrate --noinput -v 0
.venv/bin/python manage.py collectstatic --noinput -v 0

echo "Miday is running at $PUBLIC_BASE_URL  (Ctrl+C to stop)"
# One process with threads: the in-memory cache and daily Google cap stay
# shared, and all SQLite writes happen in one place.
exec .venv/bin/gunicorn config.wsgi \
  --bind "0.0.0.0:$PORT" \
  --worker-class gthread --workers 1 --threads 8 \
  --timeout 60 --access-logfile - --error-logfile -

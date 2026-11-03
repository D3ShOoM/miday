#!/usr/bin/env bash
# Set up, or update, Miday on PythonAnywhere.
# Run it in a PythonAnywhere Bash console from the project folder:
#   git clone https://github.com/D3ShOoM/miday.git ~/miday
#   cd ~/miday && bash deploy/pythonanywhere_setup.sh
# Safe to run again after `git pull`; then press Reload on the Web tab.
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR="$PWD"
HOST="$(printf '%s' "$USER" | tr '[:upper:]' '[:lower:]').${PYTHONANYWHERE_DOMAIN:-pythonanywhere.com}"
VENV="${VENV:-$HOME/.virtualenvs/miday}"

# The newest Python on this account's system image that Django 5.2 supports.
if [ -z "${PYTHON:-}" ]; then
  for version in 3.13 3.12 3.11 3.10; do
    if command -v "python$version" >/dev/null 2>&1; then PYTHON="python$version"; break; fi
  done
fi
: "${PYTHON:?No Python 3.10 or newer found}"

[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  # PythonAnywhere serves HTTPS on its own domain, and its disks are network
  # storage, where SQLite's WAL mode isn't safe.
  sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$HOST|; s|^SQLITE_WAL=.*|SQLITE_WAL=0|" .env
  {
    echo "DJANGO_DEBUG=false"
    echo "DJANGO_ALLOWED_HOSTS=$HOST"
    echo "DJANGO_SECRET_KEY=$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(50))')"
  } >> .env
  echo "Created .env for https://$HOST"
fi

"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput -v 0

PY_VERSION="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
cat <<EOF

Done. Finish on the Web tab at https://www.pythonanywhere.com/ (first time only):
  1. "Add a new web app" -> Next -> "Manual configuration" -> Python $PY_VERSION.
  2. Source code:  $APP_DIR
     Virtualenv:   $VENV
  3. Open the "WSGI configuration file" link and replace everything in it with:

$(sed "s|__APP_DIR__|$APP_DIR|g" deploy/pythonanywhere_wsgi.py)

  4. Static files: URL  /static/   Directory  $APP_DIR/staticfiles
  5. Turn on "Force HTTPS", press the green Reload button, and open https://$HOST

To update later: cd $APP_DIR && git pull && bash deploy/pythonanywhere_setup.sh, then press Reload.
EOF

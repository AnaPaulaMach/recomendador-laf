#!/bin/sh
set -e
# Aplica migraciones sobre la base local de sesiones y arranca gunicorn.
python manage.py migrate --noinput

# Diagnostico de arranque: intenta alcanzar el evaluador LAF y lo deja en el log.
python - <<'PY'
import json, os, urllib.request, urllib.error
url = os.getenv("LAF_API_URL", "")
print(f"[laf-check] LAF_API_URL={url!r} validated={os.getenv('LAF_API_RESULTS_VALIDATED')!r}")
try:
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        print(f"[laf-check] HTTP {r.status} (inesperado con payload vacio, pero hay conexion)")
except urllib.error.HTTPError as e:
    print(f"[laf-check] OK: el evaluador responde (HTTP {e.code} por payload vacio, es lo esperado)")
except Exception as e:
    print(f"[laf-check] ERROR: no se pudo conectar: {type(e).__name__}: {e}")
PY

exec gunicorn laf_web.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --access-logfile - --error-logfile -

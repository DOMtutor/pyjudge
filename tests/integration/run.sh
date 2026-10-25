#!/usr/bin/env bash
# Start a throwaway DOMjudge, run the integration tests against it, remove it.
#
#   tests/integration/run.sh [pytest options]
#
# JUDGE=1   also start a judgehost and check the verdicts of the jury solutions
#           (privileged container, needs cgroup v2)
# KEEP=1    leave the containers running afterwards (remove with
#           docker compose -f tests/integration/compose.yml down -v)
# DOMJUDGE_DOMSERVER_IMAGE=..., DOMJUDGE_JUDGEHOST_IMAGE=...   other images, e.g.
#           incaseoftrouble/domtutor_domserver:latest (default: official 9.0.1)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
compose=(docker compose -f "$here/compose.yml")
db_port=${PYJUDGE_IT_DB_PORT:-13306}
web_port=${PYJUDGE_IT_WEB_PORT:-18080}

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "--- domserver log (tail) ---"
        "${compose[@]}" exec -T domserver sh -c 'tail -n 50 /opt/domjudge/domserver/webapp/var/log*/prod.log 2>/dev/null' || true
    fi
    if [ "${KEEP:-0}" != "1" ]; then
        "${compose[@]}" --profile judge down -v --remove-orphans >/dev/null 2>&1 || true
    fi
    exit "$status"
}
trap cleanup EXIT

echo "Starting DOMjudge..."
start=$(date +%s)
"${compose[@]}" up -d --wait
echo "DOMjudge ready after $(( $(date +%s) - start )) s"

export PYJUDGE_IT_URL="http://127.0.0.1:${web_port}"
export PYJUDGE_IT_DB="127.0.0.1:${db_port}"
export PYJUDGE_IT_JUDGE=${JUDGE:-0}

if [ "${JUDGE:-0}" = "1" ]; then
    # The judgehost logs in with this password, so set it before it starts
    (cd "$root" && uv run python - <<'PY'
from pydomjudge.database import Database, update_user_password
from pydomjudge.model import User
import os
host, port = os.environ["PYJUDGE_IT_DB"].split(":")
database = Database(host=host, port=int(port), user="domjudge", password="domjudge-it", database="domjudge")
with database as db, db.transaction_cursor() as cursor:
    update_user_password(cursor, "judgehost", User.hash_password("judgehost-it"))
PY
    )
    "${compose[@]}" --profile judge up -d judgehost
fi

cd "$root"
uv run pytest -m integration tests/integration "$@"

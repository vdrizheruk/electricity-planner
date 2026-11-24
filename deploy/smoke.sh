#!/usr/bin/env bash
# End-to-end smoke test of a running deployment (docker compose or any URL).
#   deploy/smoke.sh [BASE_URL]      default http://localhost:8080 (SMOKE_SKIP_SPA=1: API only)
# Checks: probes, SPA, static files, registration, a project and the PDF/XLSX exports.
set -euo pipefail

BASE="${1:-http://localhost:8080}"
JAR="$(mktemp)"
trap 'rm -f "$JAR" /tmp/smoke.pdf /tmp/smoke.xlsx' EXIT

ok() { printf 'ok   %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

[ "$(code "$BASE/healthz")" = 200 ] || fail "/healthz"
ok "/healthz"
[ "$(code "$BASE/readyz")" = 200 ] || fail "/readyz (database unreachable?)"
ok "/readyz"
if [ "${SMOKE_SKIP_SPA:-0}" != 1 ]; then # set when only the backend is reachable
    curl -fsS "$BASE/" | grep -q 'id="root"' || fail "SPA index"
    ok "SPA index"
    [ "$(code "$BASE/projects/1/bom")" = 200 ] || fail "SPA client-side route fallback"
    ok "SPA route fallback"
fi
[ "$(code "$BASE/static/admin/css/base.css")" = 200 ] || fail "static files (WhiteNoise)"
ok "static files"

curl -fsS -c "$JAR" -b "$JAR" "$BASE/api/v1/auth/csrf/" >/dev/null
csrf="$(awk '$6 == "csrftoken" {print $7}' "$JAR")"
[ -n "$csrf" ] || fail "csrf cookie"
post() { # path json
    curl -fsS -c "$JAR" -b "$JAR" -H "X-CSRFToken: $csrf" -H "Referer: $BASE/" \
        -H 'Content-Type: application/json' -d "$2" "$BASE/api/v1$1"
}

email="smoke-$(date +%s)-$RANDOM@example.com"
post /auth/register/ "{\"email\":\"$email\",\"password\":\"Smoke-Pass-12345\"}" >/dev/null
csrf="$(awk '$6 == "csrftoken" {print $7}' "$JAR")"
ok "registration"

pid="$(post /projects/ '{"name":"Smoke"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
ok "project $pid"

n="$(curl -fsS -b "$JAR" "$BASE/api/v1/catalog/products/?page_size=1" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
[ "$n" -ge 150 ] || fail "catalog is not seeded ($n items)"
ok "catalog seeded ($n items)"

curl -fsS -b "$JAR" -o /tmp/smoke.pdf "$BASE/api/v1/projects/$pid/export/pdf/"
head -c 4 /tmp/smoke.pdf | grep -q '%PDF' || fail "PDF export"
ok "PDF export ($(wc -c </tmp/smoke.pdf) bytes)"
curl -fsS -b "$JAR" -o /tmp/smoke.xlsx "$BASE/api/v1/projects/$pid/export/xlsx/"
head -c 2 /tmp/smoke.xlsx | grep -q 'PK' || fail "XLSX export"
ok "XLSX export"

echo "smoke test passed"

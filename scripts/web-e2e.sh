#!/usr/bin/env bash
# The web UI's Playwright suite (services/web/e2e) against a real stack: a throwaway Postgres in
# Docker, the dev fixtures, the built SPA and uvicorn. Local only: CI skips it (see the hooks in
# .pre-commit-config.yaml and services/web/e2e/README.md).
#
#   scripts/web-e2e.sh [--smoke|--full|--serve] [--headed] [--no-build] [-- <playwright args>]
#
#   --smoke     the @smoke tests only (the pre-commit hook)
#   --full      every project: desktop and phone (the pre-push hook; the default)
#   --serve     start the stack, print its URL and wait (Ctrl-C stops it), for writing tests
#   --headed    show the browser
#   --no-build  use services/web/dist as it is
#
# Everything it starts is torn down on exit, whatever happens. Needs Docker, uv, Node and the
# Playwright Chromium (`npx playwright install chromium` in services/web, once).
set -euo pipefail

if [[ -n "${CI:-}" ]]; then
  echo "web-e2e: CI is set, skipping. The Playwright suite runs locally only (services/web/e2e/README.md)."
  exit 0
fi

mode=full
headed=()
build=1
extra=()
while (($#)); do
  case "$1" in
    --smoke) mode=smoke ;;
    --full) mode=full ;;
    --serve) mode=serve ;;
    --headed) headed=(--headed) ;;
    --no-build) build=0 ;;
    --) shift; extra=("$@"); break ;;
    -h | --help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "web-e2e: unknown option $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web="$root/services/web"
results="$web/test-results"
mkdir -p "$results"
server_log="$results/server.log"

say() { printf 'web-e2e: %s\n' "$*"; }
fail() { printf 'web-e2e: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || fail "Docker isn't on PATH."
command -v uv >/dev/null || fail "uv isn't on PATH."
command -v npm >/dev/null || fail "Node (npm) isn't on PATH."
command -v curl >/dev/null || fail "curl isn't on PATH."
docker info >/dev/null 2>&1 || fail "Docker isn't running."

# The image the stack's own database runs (compose.yaml), digest and all.
image="$(sed -n 's/^ *image: \(postgres:[^ ]*\).*/\1/p' "$root/compose.yaml" | head -n 1)"
[[ -n "$image" ]] || image="postgres:17.12-alpine3.24"

db_name="dayshift-e2e-$RANDOM$RANDOM"
server_pid=""

teardown() {
  local status=$?
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    # On Windows a venv's python.exe is a launcher that runs the real interpreter as its child:
    # stop the whole tree. Elsewhere the server is the process itself.
    if [[ -r "/proc/$server_pid/winpid" ]] && command -v taskkill >/dev/null; then
      MSYS_NO_PATHCONV=1 taskkill /F /T /PID "$(cat "/proc/$server_pid/winpid")" >/dev/null 2>&1 || true
    fi
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  docker rm -f "$db_name" >/dev/null 2>&1 || true
  if ((status != 0)) && [[ -s "$server_log" ]]; then
    say "the server's log is in $server_log; its last lines:"
    tail -n 25 "$server_log" >&2 || true
  fi
  exit "$status"
}
trap teardown EXIT
trap 'exit 130' INT TERM

cd "$root"

# The project's interpreter, run directly so the server is our own child and stops with it.
python="$(uv run --frozen python -c 'import sys; print(sys.executable)' | tr -d '\r')"
if command -v cygpath >/dev/null; then python="$(cygpath -u "$python")"; fi
[[ -x "$python" ]] || fail "uv didn't give a Python interpreter ($python)."

# --- Postgres -----------------------------------------------------------------------------------
say "starting Postgres ($image) as $db_name"
MSYS_NO_PATHCONV=1 docker run -d --rm --name "$db_name" -p 127.0.0.1::5432 \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=dayshift -e POSTGRES_PASSWORD=test -e POSTGRES_DB=dayshift \
  "$image" -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
db_port="$(docker port "$db_name" 5432/tcp | head -n 1 | sed 's/.*://' | tr -d '\r')"
# Over TCP, so the entrypoint's temporary init server (socket only) doesn't count as ready.
for _ in $(seq 1 120); do
  if MSYS_NO_PATHCONV=1 docker exec "$db_name" pg_isready -q -h 127.0.0.1 -U dayshift -d dayshift; then
    break
  fi
  sleep 0.5
done
MSYS_NO_PATHCONV=1 docker exec "$db_name" pg_isready -q -h 127.0.0.1 -U dayshift -d dayshift ||
  fail "Postgres didn't come up."

# --- The app's environment ----------------------------------------------------------------------
unset DISCORD_SIM_URL WEB_GUILD_ID DEADLOCK_API_BASE DISCORD_API_BASE DISCORD_GATEWAY_URL
export DEBUG=true DEV_CONTROL=true WEB_DEV_LOGIN=true DJANGO_DOTENV=off
export DJANGO_SECRET_KEY=e2e-only
export DATABASE_URL="postgres://dayshift:test@127.0.0.1:$db_port/dayshift"
export ALLOWED_HOSTS=127.0.0.1,localhost
# The dev fixtures' server (fixtures/dev/10_community.json): the web serves that community.
export DISCORD_GUILD_ID=1100000000000000001
export LOG_FORMAT=text PYTHONUNBUFFERED=1

say "migrating and seeding"
"$python" manage.py migrate --noinput >"$results/setup.log" 2>&1 || { cat "$results/setup.log" >&2; fail "migrate failed."; }
"$python" manage.py load_presets >>"$results/setup.log" 2>&1 || { cat "$results/setup.log" >&2; fail "load_presets failed."; }
"$python" manage.py dev_seed >>"$results/setup.log" 2>&1 || { cat "$results/setup.log" >&2; fail "dev_seed failed."; }

# --- The SPA ------------------------------------------------------------------------------------
cd "$web"
if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules/.package-lock.json ]]; then
  say "installing the web UI's packages (npm ci)"
  npm ci --no-audit --no-fund >"$results/npm-ci.log" 2>&1 || { cat "$results/npm-ci.log" >&2; fail "npm ci failed."; }
fi
if ((build)); then
  # Only when something the build reads is newer than the last build.
  if [[ ! -f dist/index.html ]] ||
    [[ -n "$(find src public index.html vite.config.ts package-lock.json -newer dist/index.html -print -quit 2>/dev/null)" ]]; then
    say "building the SPA"
    npm run build >"$results/build.log" 2>&1 || { cat "$results/build.log" >&2; fail "npm run build failed."; }
  else
    say "the SPA build is up to date"
  fi
fi
[[ -f dist/index.html ]] || fail "services/web/dist has no build: run without --no-build."

node -e "const fs=require('fs');const {chromium}=require('@playwright/test');process.exit(fs.existsSync(chromium.executablePath())?0:1)" ||
  fail "Playwright's Chromium isn't installed: run 'npx playwright install chromium' in services/web once."

# --- uvicorn ------------------------------------------------------------------------------------
cd "$root"
web_port="$("$python" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])' | tr -d '\r')"
base_url="http://127.0.0.1:$web_port"
say "starting uvicorn on $base_url"
"$python" -m uvicorn config.asgi:application --host 127.0.0.1 --port "$web_port" \
  --no-access-log >"$server_log" 2>&1 &
server_pid=$!
ready=0
for _ in $(seq 1 120); do
  kill -0 "$server_pid" 2>/dev/null || fail "uvicorn exited."
  if curl -fsS -o /dev/null "$base_url/readyz" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 0.5
done
((ready)) || fail "uvicorn didn't answer /readyz."

# --- Playwright ---------------------------------------------------------------------------------
cd "$web"
if [[ "$mode" == serve ]]; then
  say "serving on $base_url until Ctrl-C. Run tests against it with:"
  say "  cd services/web && BASE_URL=$base_url npx playwright test --project=desktop"
  wait "$server_pid"
  exit 0
fi
if [[ "$mode" == smoke ]]; then
  projects=(--project=smoke)
else
  projects=(--project=desktop --project=phone)
fi
say "running the $mode suite"
BASE_URL="$base_url" npx playwright test "${projects[@]}" ${headed[@]+"${headed[@]}"} ${extra[@]+"${extra[@]}"}

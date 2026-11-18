#!/bin/sh
# Runs the test suites in throwaway stacks and exits with their result. See docs/dev/README.md.
set -eu

usage() {
    cat <<'EOF'
Usage: scripts/test.sh [unit|e2e|all] [--local] [--no-build] [-- PYTEST_ARGS...]

  unit        (default) the pytest suite, -n auto, in a clean draftbot-test stack
  e2e         the browser tests in tests/e2e against the simulator, web, bot and control panel
  all         unit, then e2e; fails if either fails
  --local     run the unit suite on this machine with uv, against a tmpfs Postgres container
              (the fastest loop; needs `uv sync` once)
  --no-build  use the images already built
  -h, --help  show this help

Arguments after -- go to pytest, e.g. scripts/test.sh -- tests/test_flow.py -k ready. With `all`
they go to the unit suite only.
Every stack is torn down afterwards (down -v), pass or fail.

Env: DRAFTBOT_WAIT_TIMEOUT   seconds to wait for health checks (default 300)
     DRAFTBOT_TEST_PG_PORT   host port of the --local Postgres (default 15433)
     DRAFTBOT_TEST_PROJECT   compose project name (default draftbot-test), to run beside
                             another test stack; give that one its own TEST_EDGE_SUBNET,
                             TEST_EDGE_IP and TEST_EDGE_IP_RANGE too. --local's Postgres is
                             the project's db service, in project <name>-local
EOF
}

MODE=unit
LOCAL=0
BUILD=1
while [ $# -gt 0 ]; do
    case "$1" in
        unit | e2e | all) MODE=$1 ;;
        --local) LOCAL=1 ;;
        --no-build) BUILD=0 ;;
        -h | --help) usage; exit 0 ;;
        --) shift; break ;;
        *) printf 'Unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
if [ "$LOCAL" -eq 1 ] && [ "$MODE" = e2e ]; then
    echo "ERROR: --local only applies to the unit suite." >&2
    exit 2
fi

cd "$(dirname "$0")/.."
TIMEOUT=${DRAFTBOT_WAIT_TIMEOUT:-300}
PG_PORT=${DRAFTBOT_TEST_PG_PORT:-15433}
PROJECT=${DRAFTBOT_TEST_PROJECT:-draftbot-test}
# --local's Postgres: compose.test.yaml's db (its image, tmpfs and settings) in a project of its
# own, named after this one so a run beside another project's leaves that one's alone.
LOCAL_PROJECT=$PROJECT-local
LOCAL_PG=$LOCAL_PROJECT-pg
STARTED_PG=0
# Git Bash would turn container paths such as /var/lib/postgresql/data into Windows paths.
MSYS_NO_PATHCONV=1
MSYS2_ARG_CONV_EXCL='*'
export MSYS_NO_PATHCONV MSYS2_ARG_CONV_EXCL

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
dc() { docker compose -p "$PROJECT" -f compose.yaml -f compose.test.yaml "$@"; }
teardown() { dc --profile '*' down -v --remove-orphans >/dev/null 2>&1 || true; }
local_pg_down() {
    docker compose -p "$LOCAL_PROJECT" -f compose.yaml -f compose.test.yaml down -v --remove-orphans \
        >/dev/null 2>&1 || true
    STARTED_PG=0
}

command -v docker >/dev/null 2>&1 || fail "docker isn't on PATH. Install Docker Desktop or Docker Engine."
docker info >/dev/null 2>&1 || fail "Docker isn't running. Start Docker Desktop (or the docker service)."

# The unit suite in the tests container.
run_unit() {
    step "Unit suite in a clean $PROJECT stack"
    teardown
    rc=0
    if [ "$BUILD" -eq 1 ]; then
        dc --profile unit run --rm --build tests pytest -n auto -p no:cacheprovider "$@" || rc=$?
    else
        dc --profile unit run --rm tests pytest -n auto -p no:cacheprovider "$@" || rc=$?
    fi
    teardown
    return "$rc"
}

# The unit suite on the host, against a Postgres container on tmpfs.
run_local() {
    step "Unit suite on this machine (uv), Postgres on 127.0.0.1:$PG_PORT"
    command -v uv >/dev/null 2>&1 || fail "uv isn't on PATH. Install it from https://docs.astral.sh/uv/."
    if [ -n "$(docker ps -q --filter "name=^$LOCAL_PG\$")" ]; then
        fail "$LOCAL_PG is running: another --local run of $PROJECT, or one that was killed. Set DRAFTBOT_TEST_PROJECT to run beside it, or remove it: scripts/clean_containers.sh --project $LOCAL_PROJECT"
    fi
    local_pg_down
    STARTED_PG=1
    docker compose -p "$LOCAL_PROJECT" -f compose.yaml -f compose.test.yaml run -d --rm \
        --name "$LOCAL_PG" -p "127.0.0.1:$PG_PORT:5432" db >/dev/null \
        || { local_pg_down; fail "Couldn't start Postgres. Is port $PG_PORT free? Set DRAFTBOT_TEST_PG_PORT."; }
    # Over TCP: the image's first-boot server only listens on its socket.
    waited=0
    until docker exec "$LOCAL_PG" pg_isready -q -h 127.0.0.1 -U draftbot -d draftbot; do
        waited=$((waited + 1))
        if [ "$waited" -ge "$TIMEOUT" ]; then
            local_pg_down
            fail "Postgres wasn't ready after ${TIMEOUT}s."
        fi
        sleep 1
    done
    rc=0
    DATABASE_URL="postgres://draftbot:test@127.0.0.1:$PG_PORT/draftbot" \
        DJANGO_SECRET_KEY=test-only-not-secret DEBUG=false DEV_CONTROL=false \
        uv run --frozen pytest -n auto "$@" || rc=$?
    local_pg_down
    return "$rc"
}

# The browser suite: the whole app against the simulator, then tests/e2e in its container.
run_e2e() {
    step "End-to-end suite in a clean $PROJECT stack"
    teardown
    mkdir -p test-results/e2e
    case "$(uname -s)" in
        Linux*) DRAFTBOT_UID=$(id -u) DRAFTBOT_GID=$(id -g); export DRAFTBOT_UID DRAFTBOT_GID ;;
    esac
    build_flag=--build
    [ "$BUILD" -eq 1 ] || build_flag=--no-build
    services="chrome control-panel bot scheduler"
    # shellcheck disable=SC2086 # $services is a list
    if ! dc --profile e2e up -d "$build_flag" --wait --wait-timeout "$TIMEOUT" $services; then
        printf '\n--- docker compose ps ---\n' >&2
        dc --profile e2e ps -a >&2 || true
        printf '\n--- last log lines ---\n' >&2
        dc --profile e2e logs --no-color --tail 40 >&2 || true
        teardown
        echo "ERROR: the e2e stack didn't become healthy." >&2
        return 1
    fi
    rc=0
    # tests/e2e/pytest.ini has the options (no cache, artefacts to test-results/).
    if [ "$BUILD" -eq 1 ]; then
        dc --profile e2e run --rm --no-deps --build e2e pytest "$@" || rc=$?
    else
        dc --profile e2e run --rm --no-deps e2e pytest "$@" || rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        printf '\n--- last log lines: web bot scheduler discord-sim ---\n' >&2
        dc --profile e2e logs --no-color --tail 40 web bot scheduler discord-sim >&2 || true
        echo "Traces and screenshots: test-results/e2e/" >&2
    fi
    teardown
    return "$rc"
}

# shellcheck disable=SC2329 # invoked by the trap
interrupted() {
    teardown
    # Only the Postgres this run started: another --local run's is none of its business.
    [ "$STARTED_PG" -eq 0 ] || local_pg_down
    echo "Interrupted; the test stack is torn down." >&2
    exit 130
}
trap interrupted INT TERM

unit() {
    if [ "$LOCAL" -eq 1 ]; then run_local "$@"; else run_unit "$@"; fi
}

case "$MODE" in
    unit)
        rc=0
        unit "$@" || rc=$?
        ;;
    e2e)
        rc=0
        run_e2e "$@" || rc=$?
        ;;
    all)
        unit_rc=0
        e2e_rc=0
        unit "$@" || unit_rc=$?
        # The pytest arguments name unit tests; the e2e suite runs whole.
        run_e2e || e2e_rc=$?
        printf '\nunit: %s   e2e: %s\n' \
            "$([ "$unit_rc" -eq 0 ] && echo passed || echo "failed ($unit_rc)")" \
            "$([ "$e2e_rc" -eq 0 ] && echo passed || echo "failed ($e2e_rc)")"
        rc=$unit_rc
        [ "$rc" -ne 0 ] || rc=$e2e_rc
        ;;
esac

if [ "$rc" -eq 0 ]; then echo "Tests passed."; else echo "Tests failed (exit $rc)." >&2; fi
exit "$rc"

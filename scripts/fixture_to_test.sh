#!/bin/sh
# From nothing to a running local dev stack: the app against the Discord simulator, seeded with
# the dev fixtures, plus the control panel. Safe to re-run. See docs/dev/README.md.
set -eu

usage() {
    cat <<'EOF'
Usage: scripts/fixture_to_test.sh [--fresh] [--no-build] [--real-discord]

Builds and starts the dev stack, migrates, loads presets, seeds fixtures/dev and prints the
URLs. Re-running is safe: it updates what changed and keeps your data.

  --fresh         drop the dev database volume first and start from empty
  --no-build      use the images already built instead of rebuilding
  --real-discord  skip the simulator and the dev seed; use .env (a real bot token and guild)
  -h, --help      show this help

Env: DRAFTBOT_WAIT_TIMEOUT  seconds to wait for each health check (default 300)
     DRAFTBOT_DEV_PROJECT   compose project name (default draftbot-dev)
     DEV_EDGE_PORT DEV_WEB_PORT DEV_SIM_PORT DEV_PANEL_PORT DEV_DB_PORT
     DEV_EDGE_SUBNET DEV_EDGE_IP DEV_EDGE_IP_RANGE
                            host ports and the edge network (defaults in compose.dev.yaml),
                            to run a second stack beside the first under another project
     DEV_DB_PASSWORD        the dev database's password (default dev), set when --fresh
     DRAFTBOT_OBSERVABILITY 1 to add compose.observability.yaml (needs DB_MONITOR_PASSWORD);
                            on by itself when the project already runs the overlay
EOF
}

FRESH=0
BUILD=1
REAL=0
for arg in "$@"; do
    case "$arg" in
        --fresh) FRESH=1 ;;
        --no-build) BUILD=0 ;;
        --real-discord) REAL=1 ;;
        -h | --help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."
TIMEOUT=${DRAFTBOT_WAIT_TIMEOUT:-300}
PROJECT=${DRAFTBOT_DEV_PROJECT:-draftbot-dev}

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# The observability overlay, when asked for or already running in this project: without it, a
# re-run would recreate pgbouncer without the exporter's login.
OBS=${DRAFTBOT_OBSERVABILITY:-0}
if [ "$OBS" != 1 ] && command -v docker >/dev/null 2>&1 \
    && [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" \
        --filter label=com.docker.compose.service=prometheus 2>/dev/null)" ]; then
    echo "$PROJECT runs the observability overlay: keeping it (compose.observability.yaml)."
    OBS=1
fi
FILES="-f compose.yaml -f compose.dev.yaml"
[ "$OBS" != 1 ] || FILES="$FILES -f compose.observability.yaml"
PROFILE="--profile sim"
[ "$REAL" -eq 0 ] || PROFILE=""

# docker compose for the dev project. The simulator is behind the `sim` profile.
# shellcheck disable=SC2086 # $FILES and $PROFILE are lists of flags
dc() { docker compose -p "$PROJECT" $FILES $PROFILE "$@"; }

# Shows what state the stack is in and the recent logs of the named services, then stops.
explain_failure() {
    message=$1
    shift
    printf '\n--- docker compose ps ---\n' >&2
    dc ps -a >&2 || true
    printf '\n--- last log lines: %s ---\n' "$*" >&2
    dc logs --no-color --tail 40 "$@" >&2 || true
    fail "$message"
}

step "Checking Docker"
command -v docker >/dev/null 2>&1 || fail "docker isn't on PATH. Install Docker Desktop or Docker Engine."
docker info >/dev/null 2>&1 || fail "Docker isn't running. Start Docker Desktop (or the docker service)."
docker compose version >/dev/null 2>&1 || fail "The docker compose plugin (v2) is missing."

if [ "$REAL" -eq 1 ]; then
    [ -f .env ] || fail ".env is missing. Copy .env.example to .env and set DISCORD_TOKEN and DISCORD_GUILD_ID."
    DRAFTBOT_ENV_FILE=.env
    echo "Real-Discord mode: using .env, no simulator."
else
    if [ -f .env.dev ]; then
        echo "Using .env.dev."
    else
        cp .env.dev.example .env.dev
        echo "Created .env.dev from .env.dev.example."
    fi
    DRAFTBOT_ENV_FILE=.env.dev
fi
export DRAFTBOT_ENV_FILE

BUILD_FLAG=--build
[ "$BUILD" -eq 1 ] || BUILD_FLAG=--no-build

if [ "$FRESH" -eq 1 ]; then
    step "Dropping the dev stack and its database volume (--fresh)"
    dc down -v --remove-orphans
fi

if [ "$REAL" -eq 1 ]; then
    step "Starting the database and pgbouncer"
    dc up -d "$BUILD_FLAG" --wait --wait-timeout "$TIMEOUT" db pgbouncer \
        || explain_failure "The database or pgbouncer didn't become healthy." db pgbouncer
else
    step "Starting the database, pgbouncer and the Discord simulator"
    dc up -d "$BUILD_FLAG" --wait --wait-timeout "$TIMEOUT" db pgbouncer discord-sim \
        || explain_failure "The database, pgbouncer or the simulator didn't become healthy." \
            db pgbouncer discord-sim
fi

step "Migrating and loading presets"
if [ "$BUILD" -eq 1 ]; then
    dc run --rm --build migrate || explain_failure "Migrations or load_presets failed." db
else
    dc run --rm migrate || explain_failure "Migrations or load_presets failed." db
fi

if [ "$REAL" -eq 1 ]; then
    echo "Skipping the dev seed: fake players don't exist on a real Discord server."
else
    step "Seeding the dev fixtures (manage.py dev_seed)"
    dc run --rm --no-deps migrate python manage.py dev_seed \
        || explain_failure "dev_seed failed." discord-sim
fi

step "Starting web, bot, scheduler, edge and control-panel"
dc up -d "$BUILD_FLAG" --no-deps --wait --wait-timeout "$TIMEOUT" \
    web bot scheduler edge control-panel \
    || explain_failure "A service didn't become healthy." web bot scheduler edge control-panel

if [ "$OBS" = 1 ]; then
    step "Starting the observability overlay"
    dc up -d "$BUILD_FLAG" --wait --wait-timeout "$TIMEOUT" \
        || explain_failure "An observability service didn't become healthy." prometheus grafana
fi

# With the profile and files this run used, so `stop` stops the simulator too.
COMPOSE_HINT=$(printf '%s' "docker compose -p $PROJECT $FILES $PROFILE")
cat <<EOF

The dev stack is up.

  Web             http://localhost:${DEV_EDGE_PORT:-18080} (through the edge)
  Admin           http://localhost:${DEV_EDGE_PORT:-18080}/admin/
  Control panel   http://localhost:${DEV_PANEL_PORT:-18091}
  Web, direct     http://localhost:${DEV_WEB_PORT:-18000}
  Dev control API http://localhost:${DEV_WEB_PORT:-18000}/_control/api/
EOF
if [ "$REAL" -eq 0 ]; then
    echo "  Discord sim     http://localhost:${DEV_SIM_PORT:-18090}/_sim/state"
fi
cat <<EOF
  Postgres        127.0.0.1:${DEV_DB_PORT:-15432} (draftbot / ${DEV_DB_PASSWORD:-dev}; the app goes through pgbouncer)

Admin login: create a superuser with
  $COMPOSE_HINT exec web python manage.py createsuperuser
Logs:  $COMPOSE_HINT logs -f bot scheduler
Stop:  $COMPOSE_HINT stop      Remove everything: scripts/clean_containers.sh
EOF

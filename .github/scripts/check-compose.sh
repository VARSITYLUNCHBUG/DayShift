#!/bin/sh
# Renders every documented compose combination with `docker compose config` and fails on an
# error or a warning (an unset variable, an obsolete key). Run from the repo root with a .env
# present, as CI does: cp .env.example .env && sh .github/scripts/check-compose.sh
set -eu

cd "$(dirname "$0")/../.."
[ -f .env ] || { echo "ERROR: no .env. Copy .env.example to .env first." >&2; exit 2; }

# Every variable a file insists on (${NAME:?message}) gets a placeholder unless it is already set:
# it only needs to exist for the render.
required=$(grep -ho '[$]{[A-Za-z_][A-Za-z0-9_]*:?' compose*.yaml deploy/compose*.yaml \
    | sed 's/^[$]{//; s/:?$//' | sort -u)
for name in $required; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || export "$name=ci-placeholder"
done

failed=0
check() {
    label=$1
    shift
    if out=$(docker compose "$@" config --quiet 2>&1) && [ -z "$out" ]; then
        printf 'ok    %s\n' "$label"
    else
        printf 'FAIL  %s\n%s\n' "$label" "$out" >&2
        failed=1
    fi
}

base="-f compose.yaml"
dev="$base -f compose.dev.yaml"
test="$base -f compose.test.yaml"
prod="$base -f deploy/compose.prod.yaml"
obs="-f compose.observability.yaml"

# shellcheck disable=SC2086 # each set of -f flags is a list
{
    check "quickstart" $base
    check "quickstart + observability" $base $obs
    check "dev, real Discord" $dev
    check "dev, simulator" $dev --profile sim
    check "dev, simulator + observability" $dev $obs --profile sim
    check "test, unit" $test --profile unit
    check "test, e2e" $test --profile e2e
    check "production" $prod
    check "production + observability" $prod $obs
    check "production + observability + public Grafana" $prod $obs -f deploy/compose.grafana.yaml
}

exit "$failed"

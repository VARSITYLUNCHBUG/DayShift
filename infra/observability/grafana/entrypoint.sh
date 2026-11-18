#!/bin/sh
# Grafana's admin password comes from .env.observability (GRAFANA_ADMIN_PASSWORD), the file only
# the observability services read. Refuse to start without one: Grafana's default is admin/admin.
set -eu

if [ -z "${GRAFANA_ADMIN_PASSWORD:-}" ]; then
    echo "GRAFANA_ADMIN_PASSWORD is unset: set it in .env.observability (from .env.observability.example)." >&2
    exit 1
fi
GF_SECURITY_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD
export GF_SECURITY_ADMIN_PASSWORD
unset GRAFANA_ADMIN_PASSWORD

exec /run.sh "$@"

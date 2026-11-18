#!/bin/sh
# Writes pgbouncer's auth file from the environment, then runs pgbouncer in its place.
#
# The file lives on the container's tmpfs (/run/pgbouncer), readable only by pgbouncer's user,
# so the passwords exist only in the environment and in memory. compose.yaml sets:
#   POSTGRES_USER, POSTGRES_PASSWORD  the superuser's login, the same values as the db service's
#                                     (an operator's psql; the app's in dev and test stacks)
#   DB_APP_PASSWORD                   optional: draftbot_app's, the app's login in production
#                                     (config/app_role.py)
#   DB_MONITOR_PASSWORD               optional: draftbot_monitor's, for the pgbouncer exporter
#                                     (a stats user, so it sees SHOW output and nothing else)
set -eu

: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

umask 077
# userlist.txt is `"user" "password"`; a double quote inside a value is written twice.
quote() { printf '"%s"' "$(printf '%s' "$1" | sed 's/"/""/g')"; }
{
    printf '%s %s\n' "$(quote "$POSTGRES_USER")" "$(quote "$POSTGRES_PASSWORD")"
    if [ -n "${DB_APP_PASSWORD:-}" ]; then
        printf '%s %s\n' "$(quote draftbot_app)" "$(quote "$DB_APP_PASSWORD")"
    fi
    if [ -n "${DB_MONITOR_PASSWORD:-}" ]; then
        printf '%s %s\n' "$(quote draftbot_monitor)" "$(quote "$DB_MONITOR_PASSWORD")"
    fi
} > /run/pgbouncer/userlist.txt

exec pgbouncer /etc/pgbouncer/pgbouncer.ini

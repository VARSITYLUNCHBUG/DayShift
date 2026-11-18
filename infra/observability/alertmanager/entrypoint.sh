#!/bin/sh
# Alertmanager reads its webhooks from files, never the environment, so write them to the tmpfs,
# along with the configuration that uses them.
#   ALERTMANAGER_DISCORD_WEBHOOK_URL  optional: alerts to Discord (alertmanager.yml); without it,
#                                     nothing is posted (quiet.yml)
#   ALERTMANAGER_WATCHDOG_URL         optional: the dead man's switch the Watchdog alert pings
set -eu

umask 077
config=/etc/alertmanager/alertmanager.yml
if [ -n "${ALERTMANAGER_DISCORD_WEBHOOK_URL:-}" ]; then
    printf '%s' "$ALERTMANAGER_DISCORD_WEBHOOK_URL" > /tmp/discord-webhook
else
    echo "ALERTMANAGER_DISCORD_WEBHOOK_URL is unset: alerts are only shown, never sent." >&2
    config=/etc/alertmanager/quiet.yml
fi
if [ -n "${ALERTMANAGER_WATCHDOG_URL:-}" ]; then
    printf '%s' "$ALERTMANAGER_WATCHDOG_URL" > /tmp/watchdog-url
    cp "$config" /tmp/alertmanager.yml
else
    echo "ALERTMANAGER_WATCHDOG_URL is unset: nothing outside this host notices if it goes down." >&2
    sed '/# BEGIN watchdog-webhook/,/# END watchdog-webhook/d' "$config" > /tmp/alertmanager.yml
fi

exec /bin/alertmanager --config.file=/tmp/alertmanager.yml --storage.path=/alertmanager "$@"

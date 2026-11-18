#!/bin/sh
# The blackbox exporter doesn't read environment variables, so write EDGE_SERVER_NAME into its
# config on the tmpfs. Unset (dev and the quickstart, which have no TLS), the probe just fails.
set -eu

case "${EDGE_SERVER_NAME:-}" in
    *[!A-Za-z0-9.-]*)
        echo "EDGE_SERVER_NAME must be a host name, not ${EDGE_SERVER_NAME}." >&2
        exit 1
        ;;
esac
sed "s/\${EDGE_SERVER_NAME}/${EDGE_SERVER_NAME:-}/" /etc/blackbox/blackbox.yml > /tmp/blackbox.yml

exec /bin/blackbox_exporter --config.file=/tmp/blackbox.yml "$@"

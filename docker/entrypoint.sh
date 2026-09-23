#!/bin/sh
# Ensure the IPC socket directory exists and is writable by the current user.
# This runs as the non-root container user — no root needed.
mkdir -p /var/run/strumline
exec "$@"

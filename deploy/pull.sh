#!/bin/sh
# Nightly, from the host's crontab (PLAN.md B8: "reads the ledger and drift/runs from a nightly
# git pull; it never writes"):
#
#   17 4 * * *  /srv/ai-release-gate/deploy/pull.sh >> /var/log/gate-pull.log 2>&1
#
# Fast-forward only: the VPS checkout is never edited, so anything else is a mistake to stop on.
# The service is restarted only when the commit moved, because a pull can change the code as
# well as the record, and a running process keeps the code it started with.
set -eu
cd "$(dirname "$0")/.."
before=$(git rev-parse HEAD)
git pull --ff-only --quiet
after=$(git rev-parse HEAD)
if [ "$before" != "$after" ]; then
  echo "$(date -u +%FT%TZ) $before -> $after, restarting"
  docker compose -f deploy/compose.yaml restart service
fi

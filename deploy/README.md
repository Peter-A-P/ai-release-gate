# Deploying the dashboard

`gate.peterparker.ca` (PLAN.md B8): the read-only service in `service/`, behind Caddy for TLS,
on the shared VPS. Locally, none of this is needed: `uv sync --all-extras && uv run gate serve`
serves the same pages at http://127.0.0.1:8000.

## On the VPS

```bash
git clone https://github.com/Peter-A-P/ai-release-gate /srv/ai-release-gate
cd /srv/ai-release-gate/deploy
docker compose up -d --build
# then, in the host's crontab:
17 4 * * *  /srv/ai-release-gate/deploy/pull.sh >> /var/log/gate-pull.log 2>&1
```

DNS: an A record for `gate.peterparker.ca` pointing at the VPS, before the first start, so Caddy
can obtain its certificate. Ports 80 and 443 open.

## How it is put together, and why

- **The code comes from the checkout, not the image.** The image holds Python, uv and git and
  nothing of the project. The checkout is mounted read-only at `/repo`, and the container syncs
  the environment its lockfile names on every start. The red-team rates are regraded when the
  read model is built, so an image carrying last month's graders would serve this month's
  answers on a different yardstick.
- **Read-only.** The mount is read-only, the service answers GET only (405 otherwise), and it
  opens none of the SQLite ledgers. A test checks the method rule.
- **The nightly pull restarts the service only when the commit moved.** A pull can change code as
  well as data, and a running process keeps the code it started with. Fast-forward only: the VPS
  checkout is never edited.
- **Caddy sends a strict Content-Security-Policy.** The pages load nothing: no scripts, fonts or
  images, inline styles only.
- **If the VPS is down, nothing is lost.** The service holds no state; every number is
  reproducible from the repository with the CLI, and the drift job does not depend on it.

## What was verified, and what was not

- Verified on 2026-09-26: `docker compose config` is valid and the image builds. The service
  itself was run with `gate serve` and every page and API checked, and `tests/test_service.py`
  holds every figure on a page to the committed report that prints it.
- **Not verified: the container running.** Docker on the laptop it was built on creates
  containers but does not start any, its own welcome container included, so the first real start
  is on the VPS. Watch `docker compose logs -f service` on that first start: building the read
  model takes about a minute.
- **Not built: the OpenTelemetry collector** B8 lists. The spans worth keeping are `boundary`'s,
  one per vendor call, and every vendor call runs in GitHub Actions, which would reach a
  collector on the VPS only if it were exposed to the internet. Tracing belongs with that
  decision, not in this stack by default.
- **Not done: the VPS itself, the DNS record and the uptime ping.** Those are portfolio action 2b.

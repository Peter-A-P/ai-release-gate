# Deploying the dashboard

`gate.peterparker.ca` is **static files on Azure Static Web Apps** (PLAN.md B8.1). Nothing in
this directory is used for it; this directory is the fallback, below. Locally:
`uv sync --all-extras && uv run gate serve` serves the pages at http://127.0.0.1:8000, and
`uv run gate export --out site` writes the files that are published.

## The deployment: Azure Static Web Apps

`.github/workflows/dashboard.yml` runs nightly, on demand and on a push that changes the record
or the code that renders it. It runs `gate export`, which writes every page and JSON document the
service answers, byte for byte, plus `staticwebapp.config.json` with the headers and clean-URL
rewrites, and uploads the directory with the Static Web App's deployment token. It calls no
vendor and spends nothing.

What only the repository owner can do, once:

1. Create a Static Web App of its own (free tier), not the portfolio site's: one app serves one
   set of files to every hostname on it.
2. Put its deployment token in this repository's secrets as `AZURE_STATIC_WEB_APPS_API_TOKEN`.
   Until then the workflow builds the site and keeps it as an artifact only.
3. Add the CNAME for `gate.peterparker.ca` (DNS only, not proxied) and validate the custom domain
   in Azure.
4. Point the uptime ping at `https://gate.peterparker.ca/data/build.json`, which names the commit
   the site was built from.

Then load the live pages once in a browser with the developer console open. The pages were
checked under these exact headers locally and nothing was blocked, but 01 found a policy blocking
its own chart colours only on the live site.

**The JSON is under `/data/`, not `/api/`**, because Static Web Apps reserves `/api/` for its
Functions backend. `gate serve` still answers the old `/api/` paths with the same bytes.

## The fallback: a container on a server

Kept, unchanged, for the day a page needs to answer live questions (a filterable per-call
breakdown, say). It is the same service, run by uvicorn behind Caddy.

```bash
git clone https://github.com/Peter-A-P/ai-release-gate /srv/ai-release-gate
cd /srv/ai-release-gate/deploy
docker compose up -d --build
# then, in the host's crontab:
17 4 * * *  /srv/ai-release-gate/deploy/pull.sh >> /var/log/gate-pull.log 2>&1
```

DNS for this route would be an A record at the server, before the first start, so Caddy can
obtain its certificate, with ports 80 and 443 open.

## The fallback, how it is put together, and why

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
- **If the server is down, nothing is lost.** The service holds no state; every number is
  reproducible from the repository with the CLI, and the drift job does not depend on it.

## The fallback, what was verified and what was not

- Verified on 2026-09-27, on Docker Desktop: the image builds, the container starts from the
  checkout mounted read-only, reads its commit through git inside the container, and serves
  every page and API; POST is refused with 405. The first start took 294 seconds, most of it
  syncing the environment, which is why the healthcheck allows 600. `caddy validate` accepts the
  Caddyfile. `tests/test_service.py` holds every figure on a page to the committed report that
  prints it.
- **Not verified: Caddy serving the real domain.** It needs the DNS record and ports 80 and 443
  on the VPS to obtain a certificate, so its first real start is there.
- **Not built: the OpenTelemetry collector** B8 lists. The spans worth keeping are `boundary`'s,
  one per vendor call, and every vendor call runs in GitHub Actions, which would reach a
  collector on the VPS only if it were exposed to the internet. Tracing belongs with that
  decision, not in this stack by default.
- **Not done: the VPS itself, the DNS record and the uptime ping.** Those are portfolio action 2b.

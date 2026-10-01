# Deploying the dashboard

[gate.peterparker.ca](https://gate.peterparker.ca) is **static files on Azure Static Web Apps**
(PLAN.md B8.1), live since 2026-09-28. Nothing in
this directory is used for it; this directory is the fallback, below. Locally:
`uv sync --all-extras && uv run gate serve` serves the pages at http://127.0.0.1:8000, and
`uv run gate export --out site` writes the files that are published.

## The deployment: Azure Static Web Apps

`.github/workflows/dashboard.yml` runs nightly, on demand and on a push that changes the record
or the code that renders it. It runs `gate export`, which writes every page and JSON document the
service answers, byte for byte, plus `staticwebapp.config.json` with the headers and clean-URL
rewrites, and uploads the directory with the Static Web App's deployment token. It calls no
vendor and spends nothing.

**Then it checks the live site.** It reads `/data/build.json` back from
`https://gate.peterparker.ca` and fails unless that names the commit just built. It retries for
ten minutes while the upload propagates. This is the uptime check: GitHub emails the owner when
a scheduled run fails. An external ping was dropped because a host serving yesterday's pages
after a failed deploy still answers a ping. `build.json` is served `no-store` so a cached copy
cannot pass. Not caught: the site going down between two nightly runs.

The one-time setup, done on 2026-09-28:

1. A Static Web App of its own (free tier), not the portfolio site's: one app serves one set of
   files to every hostname on it.
2. Its deployment token in this repository's secrets as `AZURE_STATIC_WEB_APPS_API_TOKEN`.
   Without it the workflow builds the site and keeps it as an artifact only.
3. In Cloudflare, a CNAME `gate` to the app's `*.azurestaticapps.net` host, **DNS only (grey
   cloud)**. Then, and only then, the custom domain added in Azure ("Custom domain on other
   DNS", CNAME). Azure cannot write into a Cloudflare zone, so validating first fails with
   "CNAME Record is invalid". A proxied record fails the same way, because Azure then sees
   Cloudflare's addresses instead of the CNAME.

Checked on the live site on 2026-09-28:
- The certificate is issued for `gate.peterparker.ca`, valid to 2027-03-28, and HTTP redirects
  to HTTPS.
- All five headers arrive as `service/export.py` writes them.
- Every page and JSON document answers 200 with the right type at its clean URL, and an unknown
  path is 404.
- `/data/build.json` names the commit on `main`.
- Nothing on the served pages can be blocked by the policy: no script, image, stylesheet link,
  font or `url()`. The one chart is inline SVG styled inline, which `style-src 'unsafe-inline'`
  allows. 01 found its own policy blocking its chart colours only on the live site, which is why
  this check was repeated there.

**Changed 2026-10-01: the pages take peterparker.ca's look.** The front page is rewritten for a
reader who has never heard of a noise floor as well as one who will check the statistics, in the
palette and typefaces of the portfolio and of 01, 02, 08 and 12's pages. The two fonts are
committed in `service/static/fonts/` and served by the service at `/fonts/` as routes like any
other, so the export still writes only what the service answers; the policy adds
`font-src 'self'` and nothing else. The charts are HTML positioned in percentages and styled
inline, still no script and no image. Checked locally before deploying: the export served with
the config's own headers (not a bare static server), in Edge at desktop and phone width and in
dark mode, with every font and chart rendering under the policy. Repeat the header check on the
live site after the first deploy.

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
- **No OpenTelemetry collector here, by decision** (PLAN.md B8.1 step 9, 2026-09-28). Every
  vendor call runs in GitHub Actions, which would reach a collector on the VPS only if it were
  exposed to the internet. Instead `drift traces` rebuilds the spans from the ledgers as
  OTLP/JSON files that any collector reads.
- **Not done: the VPS itself.** Not needed while the site is static; it is portfolio action 2b,
  for project 04.

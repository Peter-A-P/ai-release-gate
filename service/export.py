"""The dashboard as files, for Azure Static Web Apps (PLAN.md B8.1).

Every page and every JSON document the service answers is the same for every visitor and changes
only with a commit, so it can be written once and served with nothing running. This writes the
bytes of each entry of `service.app.ROUTES`, the very bytes the service returns for that path,
plus the hosting config. It computes nothing of its own: `tests/test_service.py` holds each file
to the service byte for byte, as the service is held to the reports.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from service.app import HTML, ROUTES
from service.readmodel import ReadModel

CONFIG_FILE = "staticwebapp.config.json"

# The headers the Caddyfile sent on the VPS design, carried over. The pages load nothing from
# anywhere: no scripts, fonts or images, and styles only inline, so the policy allows exactly
# that. 01 found its own policy had been blocking its chart legend's colours on the live site
# since launch, which a plain local server cannot show; this one is checked under the policy,
# locally with the headers applied, and has to be checked again once deployed.
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def config() -> dict[str, Any]:
    """Clean URLs by explicit rewrite (/drift serves drift.html), JSON as application/json, and
    the headers above on everything.

    `/data/build.json` is never cached, and is matched before `/data/*` because the first route
    that matches wins. After each deploy the workflow reads it back to check the live site names
    the commit just built, and a cached copy from the night before would pass that check with
    stale numbers on the pages."""
    rewrites = [
        {"route": r.path, "rewrite": "/" + r.file}
        for r in ROUTES
        if r.media_type == HTML and r.path != "/"
    ]
    return {
        "routes": [
            *rewrites,
            {"route": "/data/build.json", "headers": {"Cache-Control": "no-store"}},
            {"route": "/data/*", "headers": {"Cache-Control": "public, max-age=3600"}},
        ],
        "mimeTypes": {".json": "application/json"},
        "globalHeaders": HEADERS,
    }


def export(model: ReadModel, out: Path) -> list[Path]:
    """Write the site to `out`, emptied first so a file dropped from ROUTES does not linger on
    the published site. Returns the files written."""
    if out.exists():
        shutil.rmtree(out)
    written: list[Path] = []
    for route in ROUTES:
        path = out / route.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(route.render(model))
        written.append(path)
    cfg = out / CONFIG_FILE
    cfg.write_text(json.dumps(config(), indent=2) + "\n", encoding="utf-8", newline="\n")
    written.append(cfg)
    return written

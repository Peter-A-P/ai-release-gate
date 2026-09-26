# The dashboard's runtime: Python, uv and git, and nothing of the project itself.
#
# The code AND the record come from the checkout mounted at /repo, pulled nightly (pull.sh), so
# the code that computes a number always matches the record it is computed from. The red-team
# rates are regraded when the page is built, and an image with last month's graders serving
# this month's answers would be exactly the two-yardsticks confound the project exists to remove.
FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory /repo
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/venv UV_CACHE_DIR=/uv-cache UV_LINK_MODE=copy GATE_ROOT=/repo
WORKDIR /repo
EXPOSE 8000
# Syncs the environment the checkout's lockfile names, then serves. Read-only by construction:
# the mount is read-only in compose.yaml.
CMD ["sh", "-c", "uv sync --frozen --extra gate --extra service --no-dev --no-install-project && PYTHONPATH=/repo exec /venv/bin/uvicorn service.app:app --host 0.0.0.0 --port 8000 --proxy-headers"]

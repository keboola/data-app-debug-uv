# data-app-debug-uv

Minimal Streamlit data app for debugging private PyPI / uv configuration in a Keboola data app
(component `keboola.data-apps`, base image `data-app-python-js`).

Built for [AJDA-2681](https://linear.app/keboola/issue/AJDA-2681) — SLSP stack data apps fail to
download Python packages because `pip_repositories` is not configured on the stack's
`keboola.data-apps` component image parameters.

## What it shows

1. `/data/config.json` (credentials redacted) — confirms what the stack injects
2. `~/.config/uv/uv.toml` — the file `setup_uv_config.py` writes during startup, with a warning if
   no `[[index]]` is marked `default = true` (uv would still hit PyPI as a fallback)
3. `uv` and `pip` versions
4. Network reachability for every URL in `pip_repositories` plus `pypi.org` /
   `files.pythonhosted.org`: DNS, TCP connect, HTTP HEAD via curl
5. `uv pip install --dry-run <pkg>` — resolves a package using the same indexes the real app would,
   without installing
6. Relevant env vars (`UV_*`, `PIP_*`, `KBC_*`, etc.)

## How to deploy

1. Push this repo somewhere accessible from the stack (GitHub, internal git).
2. Create a `keboola.data-apps` config and set `parameters.dataApp.git.repository` to the repo URL.
3. (Optional) Set `parameters.pip_repositories` in the config to override / supplement what the
   stack provides.
4. Run the app. Open the URL the platform exposes.

## Local smoke test

```bash
# Outside Keboola — fake /data/config.json, run streamlit directly
mkdir -p /tmp/dbg/data && cat > /tmp/dbg/data/config.json <<'JSON'
{ "pip_repositories": [{ "url": "https://pypi.org/simple/" }] }
JSON
docker run --rm -it \
  -v "$PWD":/app \
  -v /tmp/dbg/data:/data \
  -p 8888:8888 \
  ghcr.io/keboola/data-app-python-js:dev-latest
```

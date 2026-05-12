# data-app-debug-uv

Minimal data app that inspects the private PyPI / uv configuration of a Keboola data app
(component `keboola.data-apps`, base image `data-app-python-js`).

Pure stdlib — single `app.py`, no third-party dependencies. Renders one HTML page server-side per
request via `http.server`, so there are no WebSockets, no CORS / origin allowlist surprises behind
the platform's reverse proxy.

## What it shows

1. `/data/config.json` (credentials redacted) — what the platform injected
2. `~/.config/uv/uv.toml` — the file `setup_uv_config.py` writes during startup, with a warning if
   no `[[index]]` is marked `default = true` (uv would still fall back to PyPI)
3. `uv` and `pip` versions
4. Network reachability for every URL in `pip_repositories` plus `pypi.org` /
   `files.pythonhosted.org`: DNS, TCP connect, HTTP HEAD via curl
5. `uv pip install --dry-run <pkg>` — resolves a package against the configured indexes (submit
   the form with a package name to run)
6. Relevant env vars (`UV_*`, `PIP_*`, `KBC_*`, etc.)

## Deploy

1. Push this repo somewhere reachable from the target stack.
2. Create a `keboola.data-apps` config and set `parameters.dataApp.git.repository` to the repo URL.
3. (Optional) Set `parameters.pip_repositories` in the config to override / supplement what the
   stack provides.
4. Run the app and open the URL the platform exposes.

## Run locally

```bash
cd /path/to/data-app-debug-uv

cat > /tmp/config.json <<'JSON'
{ "pip_repositories": [{ "url": "https://pypi.org/simple/" }] }
JSON

CONFIG_PATH=/tmp/config.json python3 app.py
```

Open http://127.0.0.1:8501.

> Sections 2 (`~/.config/uv/uv.toml`) and 5 (`uv pip install --dry-run`) reflect your local uv
> setup, not what the base image would produce. To exercise the full entrypoint, build the base
> image from source and mount this repo as `/app`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CONFIG_PATH` | `/data/config.json` | Config file to inspect |
| `UV_CONFIG_PATH` | `~/.config/uv/uv.toml` | uv config file to display |
| `LISTEN_HOST` | `127.0.0.1` | Bind address |
| `LISTEN_PORT` | `8501` | Bind port |

# data-app-debug-uv

Minimal Streamlit data app that inspects the private PyPI / uv configuration of a Keboola data app
(component `keboola.data-apps`, base image `data-app-python-js`).

## What it shows

1. `/data/config.json` (credentials redacted) — what the platform injected
2. `~/.config/uv/uv.toml` — the file `setup_uv_config.py` writes during startup, with a warning if
   no `[[index]]` is marked `default = true` (uv would still hit PyPI as a fallback)
3. `uv` and `pip` versions
4. Network reachability for every URL in `pip_repositories` plus `pypi.org` /
   `files.pythonhosted.org`: DNS, TCP connect, HTTP HEAD via curl
5. `uv pip install --dry-run <pkg>` — resolves a package against the configured indexes without
   installing
6. Relevant env vars (`UV_*`, `PIP_*`, `KBC_*`, etc.)

## Deploy

1. Push this repo somewhere reachable from the target stack (GitHub, internal git).
2. Create a `keboola.data-apps` config and set `parameters.dataApp.git.repository` to the repo URL.
3. (Optional) Set `parameters.pip_repositories` in the config to override / supplement what the
   stack provides.
4. Run the app and open the URL the platform exposes.

## Run locally

The app can run standalone — no base image needed — by faking `/data/config.json` via an env var
override. The `CONFIG_PATH` env var lets you point at any JSON file:

```bash
cd /Users/miroslavcillik/Projects/data-app-debug-uv

# fake config
cat > /tmp/config.json <<'JSON'
{ "pip_repositories": [{ "url": "https://pypi.org/simple/" }] }
JSON

uv sync
CONFIG_PATH=/tmp/config.json uv run streamlit run app.py
```

Open http://localhost:8501.

> Sections 2 (`~/.config/uv/uv.toml`) and 5 (`uv pip install --dry-run`) will reflect your local uv
> setup, not what the base image would produce. To exercise the full entrypoint, build and run the
> base image from source instead:
>
> ```bash
> # in a checkout of keboola/data-app-python-js
> docker compose build runtime
> docker run --rm -it \
>   -v /Users/miroslavcillik/Projects/data-app-debug-uv:/repo \
>   -v /tmp/config.json:/data/config.json \
>   -e DATA_APP_GIT_REPOSITORY=file:///repo \
>   -p 8888:8888 \
>   keboola/data-app-python-js
> ```

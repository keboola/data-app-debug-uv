"""
Debug data app for diagnosing private PyPI / uv config in Keboola data apps.

What it shows:
  1. /data/config.json (credentials redacted)
  2. ~/.config/uv/uv.toml (the file written by setup_uv_config.py)
  3. uv version / pip version
  4. Network reachability:
     - Hosts listed in pip_repositories
     - pypi.org and files.pythonhosted.org (the default index)
  5. uv pip install --dry-run on a test package against the configured indexes
  6. Relevant environment variables

Drop this app into your data-app config (component: keboola.data-apps), set
parameters.dataApp.git.repository to this repo, deploy, open the URL.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/data/config.json"))
UV_CONFIG_PATH = Path(
    os.environ.get("UV_CONFIG_PATH", Path.home() / ".config" / "uv" / "uv.toml")
)

# ---------- helpers ----------

CREDENTIAL_URL_RE = re.compile(r"(https?://)([^:@/]+)(?::([^@/]+))?@")


def redact_url(url: str) -> str:
    """Replace user:pass@host with ***@host in any URL substring."""
    return CREDENTIAL_URL_RE.sub(lambda m: f"{m.group(1)}***@", url)


def redact_text(text: str) -> str:
    return CREDENTIAL_URL_RE.sub(lambda m: f"{m.group(1)}***@", text)


def redact_json(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.startswith("#") or k.lower() in {"credentials", "password", "token"}:
                out[k] = "***"
            else:
                out[k] = redact_json(v)
        return out
    if isinstance(obj, list):
        return [redact_json(v) for v in obj]
    if isinstance(obj, str):
        return redact_url(obj)
    return obj


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"


def host_port_from_url(url: str) -> tuple[str, int]:
    p = urlparse(url)
    host = p.hostname or ""
    port = p.port or (443 if p.scheme == "https" else 80)
    return host, port


# ---------- page ----------

st.set_page_config(page_title="Data App: uv / PyPI debug", layout="wide")
st.title("Data App: uv / private PyPI debug")
st.caption(
    "Inspects the propagation chain: component imageParameters → /data/config.json → "
    "~/.config/uv/uv.toml → uv pip install."
)

# 1. /data/config.json
st.header("1. /data/config.json")
if CONFIG_PATH.exists():
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        pip_repos = cfg.get("pip_repositories", [])
        if pip_repos:
            st.success(f"`pip_repositories` is present with {len(pip_repos)} entry/entries.")
        else:
            st.error(
                "`pip_repositories` is **missing or empty** in /data/config.json. "
                "This is the symptom the SLSP ticket describes: the component's "
                "imageParameters.pip_repositories is not configured on this stack."
            )
        with st.expander("Show /data/config.json (redacted)", expanded=False):
            st.code(json.dumps(redact_json(cfg), indent=2), language="json")
    except Exception as e:
        st.error(f"Failed to read /data/config.json: {e}")
        cfg, pip_repos = {}, []
else:
    st.error("/data/config.json not found.")
    cfg, pip_repos = {}, []

# 2. ~/.config/uv/uv.toml
st.header("2. ~/.config/uv/uv.toml (written by setup_uv_config.py)")
if UV_CONFIG_PATH.exists():
    try:
        content = UV_CONFIG_PATH.read_text()
        st.success(f"Found: `{UV_CONFIG_PATH}` ({len(content)} bytes)")
        st.code(redact_text(content), language="toml")
        if "default = true" not in content:
            st.warning(
                "No `default = true` on any `[[index]]`. uv will also try PyPI as the "
                "fallback default index. On a stack with egress blocked (like SLSP), "
                "any package not on the private index will still fail."
            )
    except Exception as e:
        st.error(f"Failed to read {UV_CONFIG_PATH}: {e}")
else:
    st.warning(
        f"{UV_CONFIG_PATH} does not exist. Either `pip_repositories` was empty in "
        "/data/config.json (setup_uv_config.py exits silently) or the entrypoint "
        "skipped that step."
    )

# 3. Tool versions
st.header("3. Tool versions")
col1, col2 = st.columns(2)
with col1:
    st.subheader("uv")
    rc, out, err = run(["uv", "--version"])
    st.code((out + err).strip() or f"rc={rc}")
with col2:
    st.subheader("pip")
    rc, out, err = run(["python3", "-m", "pip", "--version"])
    st.code((out + err).strip() or f"rc={rc}")

# 4. Network reachability
st.header("4. Network reachability")
candidate_urls: list[tuple[str, str]] = []
for repo in pip_repos:
    url = repo.get("url") if isinstance(repo, dict) else None
    if url:
        candidate_urls.append(("private", url))
candidate_urls.append(("default", "https://pypi.org/simple/"))
candidate_urls.append(("default", "https://files.pythonhosted.org/"))

for kind, url in candidate_urls:
    redacted = redact_url(url)
    with st.expander(f"[{kind}] {redacted}", expanded=(kind == "private")):
        host, port = host_port_from_url(url)
        # DNS
        try:
            ip = socket.gethostbyname(host)
            st.write(f"DNS: `{host}` → `{ip}`")
        except Exception as e:
            st.error(f"DNS lookup failed for `{host}`: {e}")
            continue
        # TCP connect
        try:
            with socket.create_connection((host, port), timeout=5):
                st.write(f"TCP connect to `{host}:{port}` ✅")
        except Exception as e:
            st.error(f"TCP connect to `{host}:{port}` failed: {e}")
            continue
        # HTTP HEAD via curl (uses system certs, follows redirects)
        if shutil.which("curl"):
            rc, out, err = run(
                [
                    "curl",
                    "-sS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "HTTP %{http_code} in %{time_total}s\n",
                    "--max-time",
                    "10",
                    "-I",
                    url,
                ]
            )
            st.code((out + err).strip() or f"rc={rc}")

# 5. uv pip install --dry-run
st.header("5. uv pip install --dry-run")
default_pkg = "requests"
pkg = st.text_input("Package to test resolve (won't be installed):", value=default_pkg)
if st.button("Run `uv pip install --dry-run`"):
    rc, out, err = run(
        ["uv", "pip", "install", "--dry-run", "--no-cache", pkg],
        timeout=120,
    )
    st.write(f"exit code: `{rc}`")
    if out:
        st.subheader("stdout")
        st.code(redact_text(out))
    if err:
        st.subheader("stderr")
        st.code(redact_text(err))

# 6. Environment variables (filtered)
st.header("6. Relevant environment variables")
keep_prefixes = ("UV_", "PIP_", "KBC_", "STORAGE_", "SANDBOX_", "DATA_LOADER_", "WORKSPACE_", "BRANCH_", "PYTHON")
filtered = {
    k: ("***" if any(s in k.lower() for s in ("token", "secret", "password", "key")) else v)
    for k, v in sorted(os.environ.items())
    if k.startswith(keep_prefixes)
}
st.code(json.dumps(filtered, indent=2), language="json")

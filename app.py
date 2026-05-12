"""Stdlib HTTP server that displays uv / private PyPI diagnostics for a Keboola data app.

No third-party deps; renders one HTML page server-side per request.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/data/config.json"))
UV_CONFIG_PATH = Path(
    os.environ.get("UV_CONFIG_PATH", Path.home() / ".config" / "uv" / "uv.toml")
)
LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8501"))

CRED_RE = re.compile(r"(https?://)([^:@/]+)(?::([^@/]+))?@")


def redact_url(s: str) -> str:
    return CRED_RE.sub(lambda m: f"{m.group(1)}***@", s)


def redact_text(t: str) -> str:
    return CRED_RE.sub(lambda m: f"{m.group(1)}***@", t)


def redact_json(obj):
    if isinstance(obj, dict):
        return {
            k: ("***" if k.startswith("#") or k.lower() in {"credentials", "password", "token"}
                else redact_json(v))
            for k, v in obj.items()
        }
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


def host_port(url: str) -> tuple[str, int]:
    p = urlparse(url)
    return (p.hostname or ""), (p.port or (443 if p.scheme == "https" else 80))


CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1100px;
       margin: 2rem auto; padding: 0 1rem; color: #222; line-height: 1.5; }
h1 { border-bottom: 2px solid #333; padding-bottom: 0.4rem; }
h2 { margin-top: 2.5rem; }
h3 { margin: 0 0 0.4rem 0; font-size: 1rem; }
.ok { color: #0a0; } .err { color: #c00; } .warn { color: #c80; }
pre { background: #f5f5f5; padding: 0.8rem; border-radius: 4px; overflow-x: auto;
      font-size: 0.85em; white-space: pre-wrap; word-break: break-word; }
.box { border-left: 4px solid #ccc; padding: 0.5rem 1rem; margin: 0.5rem 0; background: #fafafa; }
.box.ok { border-color: #0a0; }
.box.err { border-color: #c00; }
.box.warn { border-color: #c80; }
form { display: inline; }
input, button { font-size: 1em; padding: 0.4rem 0.6rem; }
.muted { color: #666; font-size: 0.9em; }
code { background: #f0f0f0; padding: 0.1em 0.3em; border-radius: 3px; }
"""


def section_config():
    if not CONFIG_PATH.exists():
        return (
            f'<div class="box err">{html.escape(str(CONFIG_PATH))} not found.</div>',
            [],
        )
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        return (
            f'<div class="box err">Failed to parse {html.escape(str(CONFIG_PATH))}: '
            f'{html.escape(str(e))}</div>',
            [],
        )
    pip_repos = cfg.get("pip_repositories") or []
    if pip_repos:
        badge = (
            f'<div class="box ok"><code>pip_repositories</code> present with '
            f"{len(pip_repos)} entry/entries.</div>"
        )
    else:
        badge = (
            '<div class="box err"><code>pip_repositories</code> is missing or empty '
            "in /data/config.json — the component's "
            "<code>imageParameters.pip_repositories</code> did not propagate.</div>"
        )
    pretty = html.escape(json.dumps(redact_json(cfg), indent=2))
    return f"{badge}<pre>{pretty}</pre>", pip_repos


def section_uv_toml():
    if not UV_CONFIG_PATH.exists():
        return (
            f'<div class="box warn">{html.escape(str(UV_CONFIG_PATH))} does not exist. '
            "<code>setup_uv_config.py</code> exits silently when "
            "<code>pip_repositories</code> is empty.</div>"
        )
    content = UV_CONFIG_PATH.read_text()
    out = [
        f'<div class="box ok">{html.escape(str(UV_CONFIG_PATH))} '
        f"({len(content)} bytes)</div>"
    ]
    if "default = true" not in content:
        out.append(
            '<div class="box warn">No <code>default = true</code> on any '
            "<code>[[index]]</code>. uv will still fall back to PyPI for missing "
            "packages. On a stack with egress blocked, that fallback also fails.</div>"
        )
    out.append(f"<pre>{html.escape(redact_text(content))}</pre>")
    return "".join(out)


def section_versions():
    rc1, out1, err1 = run(["uv", "--version"])
    rc2, out2, err2 = run(["python3", "-m", "pip", "--version"])
    uv_line = (out1 + err1).strip() or f"rc={rc1}"
    pip_line = (out2 + err2).strip() or f"rc={rc2}"
    return f"<pre>uv:  {html.escape(uv_line)}\npip: {html.escape(pip_line)}</pre>"


def section_network(pip_repos):
    candidates: list[tuple[str, str]] = []
    for repo in pip_repos:
        if isinstance(repo, dict) and repo.get("url"):
            candidates.append(("private", repo["url"]))
    candidates += [
        ("default", "https://pypi.org/simple/"),
        ("default", "https://files.pythonhosted.org/"),
    ]
    rows = []
    for kind, url in candidates:
        host, port = host_port(url)
        bits = [f"<h3>[{kind}] {html.escape(redact_url(url))}</h3>"]
        try:
            ip = socket.gethostbyname(host)
            bits.append(
                f"<div>DNS: <code>{html.escape(host)}</code> → "
                f"<code>{html.escape(ip)}</code></div>"
            )
        except Exception as e:
            bits.append(
                f'<div class="err">DNS lookup failed for '
                f"<code>{html.escape(host)}</code>: {html.escape(str(e))}</div>"
            )
            rows.append('<div class="box">' + "".join(bits) + "</div>")
            continue
        try:
            with socket.create_connection((host, port), timeout=5):
                bits.append(
                    f'<div class="ok">TCP <code>{html.escape(host)}:{port}</code> ✓</div>'
                )
        except Exception as e:
            bits.append(
                f'<div class="err">TCP <code>{html.escape(host)}:{port}</code> '
                f"failed: {html.escape(str(e))}</div>"
            )
            rows.append('<div class="box">' + "".join(bits) + "</div>")
            continue
        if shutil.which("curl"):
            rc, out, err = run(
                [
                    "curl", "-sS", "-o", "/dev/null",
                    "-w", "HTTP %{http_code} in %{time_total}s",
                    "--max-time", "10", "-I", url,
                ]
            )
            line = (out + err).strip() or f"rc={rc}"
            bits.append(f"<pre>{html.escape(line)}</pre>")
        rows.append('<div class="box">' + "".join(bits) + "</div>")
    return "".join(rows)


def section_dryrun(pkg: str):
    if not pkg:
        return ""
    rc, out, err = run(
        [
            "uv", "pip", "install", "--dry-run", "--no-cache",
            "--system", "--break-system-packages", pkg,
        ],
        timeout=120,
    )
    return (
        f"<div>exit code: <code>{rc}</code></div>"
        f"<h4>stdout</h4><pre>{html.escape(redact_text(out)) or '(empty)'}</pre>"
        f"<h4>stderr</h4><pre>{html.escape(redact_text(err)) or '(empty)'}</pre>"
    )


def section_env():
    keep = (
        "UV_", "PIP_", "KBC_", "STORAGE_", "SANDBOX_", "DATA_LOADER_",
        "WORKSPACE_", "BRANCH_", "PYTHON",
    )
    filt = {
        k: ("***" if any(s in k.lower() for s in ("token", "secret", "password", "key")) else v)
        for k, v in sorted(os.environ.items())
        if k.startswith(keep)
    }
    return f"<pre>{html.escape(json.dumps(filt, indent=2))}</pre>"


def render_page(query: dict[str, list[str]]) -> str:
    pkg = (query.get("pkg") or [""])[0]
    cfg_html, pip_repos = section_config()
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>uv / PyPI debug</title><style>{CSS}</style></head>
<body>
<h1>Data App: uv / private PyPI debug</h1>
<p class="muted">Inspects the propagation chain: component <code>imageParameters</code> →
<code>/data/config.json</code> → <code>~/.config/uv/uv.toml</code> →
<code>uv pip install</code>.</p>

<h2>1. /data/config.json</h2>
{cfg_html}

<h2>2. ~/.config/uv/uv.toml</h2>
{section_uv_toml()}

<h2>3. Tool versions</h2>
{section_versions()}

<h2>4. Network reachability</h2>
{section_network(pip_repos)}

<h2>5. uv pip install --dry-run</h2>
<form method="get" action="/">
  <label>Package: <input name="pkg" value="{html.escape(pkg or 'requests')}"></label>
  <button type="submit">Run dry-run</button>
</form>
{section_dryrun(pkg)}

<h2>6. Relevant environment variables</h2>
{section_env()}

</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        body = render_page(parse_qs(parsed.query)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(
            f"{self.address_string()} - - [{self.log_date_time_string()}] "
            f"{fmt % args}\n"
        )


if __name__ == "__main__":
    print(f"Serving on http://{LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()

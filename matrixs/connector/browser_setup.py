from __future__ import annotations

import html
import secrets
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

from matrixs.config import DEFAULT_API_URL

from .models import Credentials


MAX_FORM_BYTES = 16 * 1024


def _valid_api_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _setup_page(
    *,
    state: str,
    project_name: str,
    project_id: str,
    api_url: str,
    error: str = "",
) -> bytes:
    safe_state = html.escape(state, quote=True)
    safe_name = html.escape(project_name, quote=True)
    safe_project_id = html.escape(project_id, quote=True)
    safe_api_url = html.escape(api_url, quote=True)
    error_html = (
        f'<div class="alert" role="alert">{html.escape(error)}</div>' if error else ""
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect your project | Matrixs</title>
  <style>
    :root {{ color-scheme: light; --ink:#172235; --muted:#64718a; --line:#d7dfec; --blue:#2f64ef; --blue-dark:#204dcc; --soft:#f3f7ff; --green:#087d55; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:linear-gradient(145deg,#eef4ff 0%,#fff 52%,#f5fbf9 100%); color:var(--ink); font:16px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; min-height:100vh; }}
    a {{ color:var(--blue-dark); }}
    .skip {{ position:absolute; left:-9999px; }}
    .skip:focus {{ left:18px; top:18px; z-index:2; background:white; padding:10px 14px; border-radius:8px; outline:3px solid var(--blue); }}
    header {{ background:rgba(255,255,255,.9); border-bottom:1px solid var(--line); padding:16px 24px; }}
    .brand {{ display:flex; align-items:center; gap:12px; max-width:760px; margin:auto; font-weight:800; }}
    .mark {{ display:grid; place-items:center; width:34px; height:34px; border-radius:10px; background:var(--blue); color:white; }}
    main {{ width:min(760px,calc(100% - 32px)); margin:48px auto; }}
    .card {{ background:white; border:1px solid var(--line); border-radius:20px; box-shadow:0 18px 55px rgba(38,62,112,.12); overflow:hidden; }}
    .intro {{ padding:32px 32px 24px; background:linear-gradient(135deg,#fff,#f7f9ff); border-bottom:1px solid var(--line); }}
    .eyebrow {{ margin:0 0 8px; color:var(--blue-dark); font-size:13px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ margin:0; font-size:clamp(30px,6vw,44px); line-height:1.08; letter-spacing:-.035em; }}
    .lead {{ color:var(--muted); margin:14px 0 0; }}
    .privacy {{ margin:18px 0 0; padding:12px 14px; background:#edf9f4; border:1px solid #bfe7d6; border-radius:10px; color:#075b40; font-size:14px; }}
    form {{ padding:28px 32px 32px; }}
    fieldset {{ border:0; padding:0; margin:0; }}
    legend {{ font-size:20px; font-weight:800; margin-bottom:18px; }}
    .field {{ margin-bottom:18px; }}
    label {{ display:block; font-weight:750; margin-bottom:7px; }}
    .required {{ color:#b42318; }}
    input {{ width:100%; border:1px solid #bdc9dd; border-radius:10px; padding:12px 13px; font:inherit; color:var(--ink); background:white; }}
    input:focus-visible, button:focus-visible, summary:focus-visible, a:focus-visible {{ outline:3px solid rgba(47,100,239,.35); outline-offset:2px; }}
    .help {{ display:block; margin-top:6px; color:var(--muted); font-size:13px; }}
    details {{ margin:4px 0 22px; }}
    summary {{ cursor:pointer; color:var(--blue-dark); font-weight:700; }}
    details .field {{ margin:14px 0 0; }}
    .actions {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:8px; }}
    button {{ border:0; border-radius:10px; padding:12px 18px; font:inherit; font-weight:800; cursor:pointer; }}
    .primary {{ background:var(--blue); color:white; }}
    .primary:hover {{ background:var(--blue-dark); }}
    .secondary {{ background:#edf1f7; color:var(--ink); }}
    .alert {{ margin:0 32px; transform:translateY(18px); padding:12px 14px; border:1px solid #f3b9b2; border-radius:10px; background:#fff0ef; color:#8f1e14; }}
    .manual {{ margin:18px 0 0; color:var(--muted); font-size:14px; }}
    @media (max-width:560px) {{ main {{ margin:24px auto; }} .intro,form {{ padding:24px 20px; }} .alert {{ margin:0 20px; }} .actions button {{ width:100%; }} }}
    @media (prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto!important; transition:none!important; }} }}
  </style>
</head>
<body>
  <a class="skip" href="#connection-form">Skip to connection form</a>
  <header><div class="brand"><span class="mark" aria-hidden="true">M</span><span>Matrixs</span></div></header>
  <main>
    <section class="card" aria-labelledby="page-title">
      <div class="intro">
        <p class="eyebrow">Local secure setup</p>
        <h1 id="page-title">Finish connecting {safe_name}</h1>
        <p class="lead">Enter the Project ID and API key from your Matrixs project. After you submit, the terminal will create the integration files, save the credentials locally, and verify the connection.</p>
        <p class="privacy"><strong>Private by design:</strong> this page is served only on your computer. Your API key is posted to the local Matrixs CLI and is never placed in the command or URL.</p>
      </div>
      {error_html}
      <form id="connection-form" method="post" action="/connect?state={safe_state}">
        <fieldset>
          <legend>Matrixs project credentials</legend>
          <div class="field">
            <label for="project-id">Project ID <span class="required" aria-hidden="true">*</span><span class="required" style="position:absolute;left:-9999px"> (required)</span></label>
            <input id="project-id" name="project_id" value="{safe_project_id}" placeholder="prj_..." required aria-describedby="project-id-help" autocomplete="off" spellcheck="false" autofocus>
            <span id="project-id-help" class="help">Copy this from Project Connection in Matrixs.</span>
          </div>
          <div class="field">
            <label for="api-key">API key <span class="required" aria-hidden="true">*</span><span class="required" style="position:absolute;left:-9999px"> (required)</span></label>
            <input id="api-key" name="api_key" type="password" placeholder="mx_..." required aria-describedby="api-key-help" autocomplete="off" spellcheck="false">
            <span id="api-key-help" class="help">The key is saved to .matrixs/.env, which Matrixs adds to .gitignore.</span>
          </div>
          <div class="field">
            <label for="project-name">Project name</label>
            <input id="project-name" name="project_name" value="{safe_name}" autocomplete="off">
          </div>
          <details>
            <summary>Advanced: Matrixs Cloud address</summary>
            <div class="field">
              <label for="api-url">API URL</label>
              <input id="api-url" name="api_url" type="url" value="{safe_api_url}" required spellcheck="false">
            </div>
          </details>
        </fieldset>
        <div class="actions">
          <button class="primary" type="submit">Save and complete integration</button>
          <button class="secondary" type="submit" formaction="/cancel?state={safe_state}" formnovalidate>Cancel</button>
        </div>
        <p class="manual">Need the values? Open <a href="https://software-reliability-engine.onrender.com/api-keys" target="_blank" rel="noreferrer">Project Connection</a>. Prefer to add everything yourself? Cancel and choose manual integration in the terminal.</p>
      </form>
    </section>
  </main>
</body>
</html>"""
    return page.encode("utf-8")


def _result_page(*, success: bool, message: str) -> bytes:
    color = "#087d55" if success else "#8f1e14"
    title = "Credentials received" if success else "Setup cancelled"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | Matrixs</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f7ff;color:#172235;font:16px/1.5 system-ui,sans-serif}}main{{width:min(560px,calc(100% - 32px));padding:34px;background:white;border:1px solid #d7dfec;border-radius:18px;box-shadow:0 18px 55px rgba(38,62,112,.12)}}h1{{margin:0 0 10px;color:{color};font-size:32px}}p{{margin:0;color:#64718a}}</style></head><body><main><h1>{title}</h1><p>{html.escape(message)}</p></main></body></html>"""
    return page.encode("utf-8")


def collect_credentials_in_browser(
    project_root: Path,
    *,
    project_id: str = "",
    project_name: str = "",
    api_url: str = DEFAULT_API_URL,
    timeout: float = 600.0,
    browser_open: Callable[[str], object] = webbrowser.open,
) -> Credentials:
    """Collect secrets through a nonce-protected form bound only to loopback."""

    root = project_root.resolve()
    state = secrets.token_urlsafe(24)
    values: dict[str, str] = {}
    outcome = {"cancelled": False}
    defaults = {
        "project_id": project_id.strip(),
        "project_name": project_name.strip() or root.name,
        "api_url": api_url.strip().rstrip("/") or DEFAULT_API_URL,
    }

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _authorized_path(self, expected: str) -> bool:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            return parsed.path == expected and query.get("state") == [state]

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if not self._authorized_path("/"):
                self._send(404, _result_page(success=False, message="This local setup link is invalid."))
                return
            self._send(200, _setup_page(state=state, **defaults))

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self._authorized_path("/cancel"):
                outcome["cancelled"] = True
                self._send(200, _result_page(success=False, message="No files were changed. You can close this tab."))
                return
            if not self._authorized_path("/connect"):
                self._send(404, _result_page(success=False, message="This local setup link is invalid."))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_FORM_BYTES:
                self._send(413, _result_page(success=False, message="The submitted form was invalid."))
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            submitted = {key: (form.get(key) or [""])[0].strip() for key in ("project_id", "api_key", "project_name", "api_url")}
            error = ""
            if not submitted["project_id"]:
                error = "Project ID is required."
            elif not submitted["api_key"]:
                error = "API key is required."
            elif not _valid_api_url(submitted["api_url"]):
                error = "API URL must be a valid http:// or https:// address."
            if error:
                defaults.update({key: value for key, value in submitted.items() if key != "api_key"})
                self._send(400, _setup_page(state=state, error=error, **defaults))
                return
            values.update(submitted)
            self._send(200, _result_page(success=True, message="Return to the terminal while Matrixs applies and verifies the integration."))

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.25
    local_url = f"http://127.0.0.1:{server.server_port}/?state={state}"
    print("Opening the secure Matrixs credential page in your browser...")
    print(f"If it does not open automatically, visit: {local_url}")
    try:
        browser_open(local_url)
        deadline = time.monotonic() + timeout
        while not values and not outcome["cancelled"] and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if outcome["cancelled"]:
        raise ValueError("Matrixs setup was cancelled. No files were changed.")
    if not values:
        raise TimeoutError("Matrixs credential setup timed out. Run `matrixs connect` to try again.")
    return Credentials(
        project_id=values["project_id"],
        api_key=values["api_key"],
        api_url=values["api_url"].rstrip("/"),
        project_name=values["project_name"] or root.name,
        installation_id=f"inst_{uuid.uuid4().hex}",
    )

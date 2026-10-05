"""Account linking: Syllabuddy as an OAuth 2.1 authorization server.

Alexa+ add-ons that keep per-user data link accounts with OAuth 2.1 and PKCE.
The MCP SDK implements the protocol (metadata, dynamic client registration,
/authorize, /token, /revoke, bearer checks on /mcp); this module supplies the
storage and the one page a person sees: "link your Syllabuddy account".

A Syllabuddy account is a username and a PIN, created on first sign-in. After
linking, the token's subject (``user:<name>``) keys the student's history, so
the same revision list follows them from Alexa+ to the web app to any other
MCP client they link.

The simulated Alexa+ web app is a first-party client: it presents a server
token (``SYLLABUDDY_APP_TOKEN``) and names its per-browser student in the
``X-Syllabuddy-Student`` header, the way it did before accounts existed.

Everything is stored in the same SQLite file as study history. Tokens and
codes are stored only as SHA-256 hashes; PINs as salted scrypt hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SCOPE = "syllabuddy"
ACCESS_TTL = 3600                 # 1 hour
REFRESH_TTL = 60 * 60 * 24 * 60   # 60 days: students shouldn't have to re-link every week
CODE_TTL = 300
PENDING_TTL = 900
APP_CLIENT_ID = "syllabuddy-web"
USERNAME = re.compile(r"^[a-z0-9_.-]{3,32}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
    username TEXT PRIMARY KEY, pin_hash TEXT NOT NULL, salt TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('code', 'access', 'refresh')),
    data       TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _pin_hash(pin: str, salt: bytes) -> str:
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1).hex()


class SyllabuddyOAuthProvider:
    """OAuthAuthorizationServerProvider backed by SQLite, with a username + PIN sign-in page."""

    def __init__(self, db_path: str | Path, public_url: str, app_token: str | None = None) -> None:
        self.public_url = public_url.rstrip("/")
        self.app_token = app_token or None
        self._lock = threading.Lock()
        self._db = sqlite3.connect(Path(db_path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.commit()
        # Authorization requests waiting for the person to sign in, by one-time id.
        self._pending: dict[str, tuple[float, str, AuthorizationParams]] = {}

    # ---- storage helpers --------------------------------------------------------

    def _exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            self._db.commit()
            return rows

    def _put(self, kind: str, token: str, data: dict, expires_at: float) -> None:
        self._exec("INSERT OR REPLACE INTO oauth_tokens VALUES (?, ?, ?, ?)",
                   (_hash(token), kind, json.dumps(data), expires_at))

    def _get(self, kind: str, token: str) -> dict | None:
        rows = self._exec("SELECT data, expires_at FROM oauth_tokens WHERE token_hash = ? AND kind = ?",
                          (_hash(token), kind))
        if not rows:
            return None
        data, expires_at = rows[0]
        if expires_at < time.time():
            self._exec("DELETE FROM oauth_tokens WHERE token_hash = ?", (_hash(token),))
            return None
        return json.loads(data)

    def _delete(self, token: str) -> None:
        self._exec("DELETE FROM oauth_tokens WHERE token_hash = ?", (_hash(token),))

    # ---- clients (dynamic client registration) ------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        rows = self._exec("SELECT info FROM oauth_clients WHERE client_id = ?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(rows[0][0]) if rows else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._exec("INSERT OR REPLACE INTO oauth_clients VALUES (?, ?, ?)",
                   (client_info.client_id, client_info.model_dump_json(), time.time()))

    # ---- authorization: send the person to the sign-in page ------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        now = time.time()
        for key in [k for k, (t, _, _) in self._pending.items() if now - t > PENDING_TTL]:
            self._pending.pop(key, None)
        request_id = secrets.token_urlsafe(24)
        self._pending[request_id] = (now, client.client_id, params)
        return f"{self.public_url}/link?{urlencode({'request': request_id})}"

    async def sign_in_page(self, request: Request) -> Response:
        """GET shows the form; POST checks or creates the account and finishes the redirect."""
        request_id = request.query_params.get("request", "")
        pending = self._pending.get(request_id)
        if pending is None:
            return HTMLResponse(_page("This sign-in link has expired. Go back and connect Syllabuddy again."),
                                status_code=400)
        _, client_id, params = pending
        client = await self.get_client(client_id)
        client_name = (client.client_name if client and client.client_name else "An app")
        if request.method == "GET":
            return HTMLResponse(_page(_form(request_id, client_name)))

        form = await request.form()
        if form.get("action") == "deny":
            self._pending.pop(request_id, None)
            return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), error="access_denied",
                                                           state=params.state), status_code=302)
        username = str(form.get("username", "")).strip().lower()
        pin = str(form.get("pin", "")).strip()
        error = None
        if not USERNAME.match(username):
            error = "Usernames are 3 to 32 letters, numbers, dots, dashes or underscores."
        elif not re.fullmatch(r"\d{4,8}", pin):
            error = "Your PIN is 4 to 8 digits."
        elif not self._check_or_create(username, pin):
            error = "That PIN doesn't match this username."
        if error:
            return HTMLResponse(_page(_form(request_id, client_name, error, username)), status_code=400)

        self._pending.pop(request_id, None)
        code = secrets.token_urlsafe(32)
        self._put("code", code, {
            "client_id": client_id, "scopes": params.scopes or [SCOPE], "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource, "subject": f"user:{username}", "expires_at": time.time() + CODE_TTL,
        }, time.time() + CODE_TTL)
        return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state),
                                status_code=302)

    def _check_or_create(self, username: str, pin: str) -> bool:
        rows = self._exec("SELECT pin_hash, salt FROM accounts WHERE username = ?", (username,))
        if rows:
            stored, salt = rows[0]
            return hmac.compare_digest(stored, _pin_hash(pin, bytes.fromhex(salt)))
        salt = secrets.token_bytes(16)
        self._exec("INSERT INTO accounts VALUES (?, ?, ?, ?)", (username, _pin_hash(pin, salt), salt.hex(), time.time()))
        return True

    # ---- codes and tokens ------------------------------------------------------------

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        data = self._get("code", authorization_code)
        if data is None or data["client_id"] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, **data)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code) -> OAuthToken:
        self._delete(authorization_code.code)  # single use
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.subject,
                           authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        data = self._get("refresh", refresh_token)
        if data is None or data["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, **data)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token, scopes: list[str]) -> OAuthToken:
        if scopes and not set(scopes) <= set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Cannot widen the scopes of a refresh token.")
        self._delete(refresh_token.token)  # rotate
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.subject,
                           refresh_token.resource)

    def _issue(self, client_id: str, scopes: list[str], subject: str | None, resource: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        common = {"client_id": client_id, "scopes": scopes, "subject": subject, "resource": resource}
        self._put("access", access, common | {"expires_at": int(now + ACCESS_TTL)}, now + ACCESS_TTL)
        self._put("refresh", refresh, common | {"expires_at": int(now + REFRESH_TTL), "access": _hash(access)},
                  now + REFRESH_TTL)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL,
                          scope=" ".join(scopes), refresh_token=refresh)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if self.app_token and hmac.compare_digest(token, self.app_token):
            # The first-party web app: it names its own per-browser students.
            return AccessToken(token=token, client_id=APP_CLIENT_ID, scopes=[SCOPE])
        data = self._get("access", token)
        return AccessToken(token=token, **data) if data else None

    async def revoke_token(self, token) -> None:
        self._delete(token.token)
        if isinstance(token, RefreshToken):
            rows = self._exec("SELECT data FROM oauth_tokens WHERE token_hash = ?", (_hash(token.token),))
            for (data,) in rows:
                access = json.loads(data).get("access")
                if access:
                    self._exec("DELETE FROM oauth_tokens WHERE token_hash = ?", (access,))

    def forget_account(self, username: str) -> None:
        """Remove an account and every token issued to it (used by clear_my_history)."""
        self._exec("DELETE FROM accounts WHERE username = ?", (username,))
        rows = self._exec("SELECT token_hash, data FROM oauth_tokens")
        for token_hash, data in rows:
            if json.loads(data).get("subject") == f"user:{username}":
                self._exec("DELETE FROM oauth_tokens WHERE token_hash = ?", (token_hash,))


# ---- the sign-in page ----------------------------------------------------------------
# Matches the app's look (dark, cyan ring). Plain HTML, no scripts, every value escaped.

def _form(request_id: str, client_name: str, error: str | None = None, username: str = "") -> str:
    err = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return f"""
<h1>Link your Syllabuddy account</h1>
<p class="lead"><b>{html.escape(client_name)}</b> wants to use Syllabuddy as you: check your exams' syllabuses,
quiz you, and keep your revision list and saved courses.</p>
{err}
<form method="post" action="/link?{urlencode({'request': request_id})}">
  <label>Username <input name="username" autocomplete="username" required minlength="3" maxlength="32"
    pattern="[A-Za-z0-9_.\\-]+" value="{html.escape(username)}" autofocus></label>
  <label>PIN (4 to 8 digits) <input name="pin" type="password" inputmode="numeric" autocomplete="current-password"
    required pattern="[0-9]{{4,8}}"></label>
  <p class="hint">New here? Pick a username and PIN and your account is created. No email, no real name needed.</p>
  <div class="row">
    <button name="action" value="allow" class="primary">Link account</button>
    <button name="action" value="deny" formnovalidate>Cancel</button>
  </div>
</form>
<p class="fine">Syllabuddy stores only the questions you ask and your quiz results, to build your revision list.
You can delete everything any time by asking it to clear your history.
<a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></p>"""


def _page(body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Link Syllabuddy</title>
<style>
:root {{ --bg:#070b14; --ink:#eef3fb; --muted:#8d9ab3; --cyan:#00caff; --blue:#2f6bff; --red:#ff6b7a; --line:rgba(255,255,255,.09); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:24px 16px; color:var(--ink);
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif; background:radial-gradient(800px 500px at 50% -10%, rgba(0,202,255,.12), transparent 60%), var(--bg); }}
main {{ width:100%; max-width:440px; padding:32px 28px; border-radius:22px; border:1px solid var(--line); background:rgba(255,255,255,.04); }}
.ring {{ width:44px; height:44px; border-radius:50%; background:conic-gradient(from 200deg,var(--blue),var(--cyan),#7ff0ff,var(--blue));
  -webkit-mask:radial-gradient(circle,transparent 12px,#000 13px); mask:radial-gradient(circle,transparent 12px,#000 13px); margin-bottom:18px; }}
h1 {{ font-size:24px; margin:0 0 10px; letter-spacing:-.3px; }}
.lead {{ color:#c6d1e4; line-height:1.5; margin:0 0 18px; }}
label {{ display:block; font-size:14px; color:var(--muted); margin:0 0 14px; }}
input {{ display:block; width:100%; margin-top:6px; padding:12px 14px; border-radius:12px; border:1px solid var(--line);
  background:#0b1222; color:var(--ink); font-size:16px; }}
input:focus {{ outline:2px solid var(--cyan); outline-offset:1px; }}
.hint, .fine {{ font-size:13px; color:var(--muted); line-height:1.5; }}
.fine a {{ color:var(--cyan); }}
.row {{ display:flex; gap:10px; margin:18px 0; }}
button {{ flex:1; padding:12px; border-radius:12px; border:1px solid var(--line); background:transparent; color:var(--ink); font-size:15px; cursor:pointer; }}
button.primary {{ background:linear-gradient(180deg,#1d3a73,#183064); border-color:rgba(0,202,255,.4); font-weight:600; }}
.err {{ color:var(--red); background:rgba(255,107,122,.1); border:1px solid rgba(255,107,122,.3); padding:10px 12px; border-radius:10px; font-size:14px; }}
</style></head><body><main><div class="ring" aria-hidden="true"></div>{body}</main></body></html>"""

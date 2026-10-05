"""Account linking end to end, against the one-port deployment (deploy/serve.py).

What Alexa+ (or Claude, or any MCP client) does to link a Syllabuddy account:
register itself, send the student to /authorize with PKCE, the student signs in
on /link, the client trades the code for tokens, then calls /mcp with them.
"""

import asyncio
import base64
import hashlib
import os
import secrets
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from assistant.agent import _result_data
from tests.conftest import ROOT, _free_port

REDIRECT = "http://127.0.0.1:9/callback"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ | {"PORT": str(port), "SYLLABUDDY_PUBLIC_URL": base, "SYLLABUDDY_BRAIN": "offline",
                        "SYLLABUDDY_DB": str(tmp_path_factory.mktemp("acct") / "p.db"),
                        "SYLLABUDDY_APP_TOKEN": "test-app-token", "SYLLABUDDY_RATE_LIMIT": "0",
                        "PYTHONIOENCODING": "utf-8"}
    log = open(tmp_path_factory.mktemp("logs") / "serve.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "deploy.serve"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 300
    while time.time() < deadline:
        assert proc.poll() is None, "deploy.serve exited"
        try:
            if httpx.get(f"{base}/api/health", timeout=30).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    yield base
    proc.terminate()
    proc.wait(timeout=10)
    log.close()


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def link(base, username, pin, client_name="Alexa+ (test)"):
    """Run the whole OAuth 2.1 flow a client would, returning (client_id, token response)."""
    with httpx.Client(base_url=base, timeout=60) as http:
        reg = http.post("/register", json={"redirect_uris": [REDIRECT], "client_name": client_name,
                                           "token_endpoint_auth_method": "none",
                                           "grant_types": ["authorization_code", "refresh_token"],
                                           "response_types": ["code"]})
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]
        verifier, challenge = _pkce()
        auth = http.get("/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
                                              "code_challenge": challenge, "code_challenge_method": "S256",
                                              "state": "xyz", "scope": "syllabuddy"})
        assert auth.status_code == 302, auth.text
        page = auth.headers["location"]
        assert "/link?request=" in page
        form = http.get(page)
        assert form.status_code == 200 and client_name in form.text
        signed = http.post(page, data={"username": username, "pin": pin, "action": "allow"})
        if signed.status_code != 302:
            return client_id, signed
        back = urlparse(signed.headers["location"])
        query = parse_qs(back.query)
        assert query["state"] == ["xyz"]
        tokens = http.post("/token", data={"grant_type": "authorization_code", "code": query["code"][0],
                                           "redirect_uri": REDIRECT, "client_id": client_id,
                                           "code_verifier": verifier})
        assert tokens.status_code == 200, tokens.text
        return client_id, tokens.json()


async def _calls(url, headers, calls):
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(create_mcp_http_client(headers=headers))
        client = await stack.enter_async_context(Client(streamable_http_client(url, http_client=http)))
        return [_result_data(await client.call_tool(name, args)) for name, args in calls]


def call(base, token, *calls, extra=None):
    return asyncio.run(_calls(f"{base}/mcp", {"Authorization": f"Bearer {token}", **(extra or {})}, list(calls)))


def test_mcp_requires_a_token_and_says_where_to_get_one(site):
    r = httpx.post(f"{site}/mcp", json={}, timeout=30)
    assert r.status_code == 401
    assert "resource_metadata" in r.headers.get("www-authenticate", "")
    meta = httpx.get(f"{site}/.well-known/oauth-authorization-server", timeout=30).json()
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["registration_endpoint"].endswith("/register")


def test_linked_account_keeps_history_across_devices(site):
    _, tokens = link(site, "maya.k", "2468", "Alexa+ (test)")
    [saved] = call(site, tokens["access_token"],
                   ("set_my_courses", {"courses": ["SAT"], "exam_date": "2099-03-14"}))
    assert saved["saved"] is True
    # Same student, another client (say, Claude on a laptop): her courses are already there.
    _, other = link(site, "maya.k", "2468", "Claude (test)")
    [revision] = call(site, other["access_token"], ("my_revision_list", {}))
    assert [c["subject"] for c in revision["my_courses"]] == ["SAT Math (SATM)", "SAT Reading and Writing (SATRW)"]


def test_wrong_pin_is_refused(site):
    link(site, "sam.r", "1357")
    _, response = link(site, "sam.r", "9999")
    assert response.status_code == 400 and "match this username" in response.text


def test_refresh_token_rotates(site):
    client_id, tokens = link(site, "lee.j", "1111")
    with httpx.Client(base_url=site, timeout=60) as http:
        fresh = http.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                          "client_id": client_id})
        assert fresh.status_code == 200, fresh.text
        reused = http.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                           "client_id": client_id})
        assert reused.status_code == 400
    [subjects] = call(site, fresh.json()["access_token"], ("list_subjects", {}))
    assert len(subjects["subjects"]) > 40


def test_web_app_works_through_the_same_server(site):
    r = httpx.post(f"{site}/api/ask", json={"text": "Are circles on the PSAT 8/9?", "session": "s", "student": "web1"},
                   timeout=300)
    assert r.status_code == 200
    assert '"verdict": "excluded"' in r.text

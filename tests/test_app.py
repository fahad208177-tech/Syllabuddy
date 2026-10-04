"""The web app's HTTP API, using the offline brain against the real MCP server."""

import json

import pytest
from starlette.testclient import TestClient

import assistant.app as web
from assistant.agent import Assistant, OfflineBrain


@pytest.fixture()
def client(server_url, monkeypatch):
    monkeypatch.setattr(web, "assistant", Assistant(OfflineBrain(), server_url))
    return TestClient(web.app)


def test_index_and_static(client):
    page = client.get("/")
    assert page.status_code == 200 and "Syllabuddy" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_health_reports_mcp_and_tools(client):
    health = client.get("/api/health").json()
    assert health["mcp_ok"] is True and health["brain"] == "offline"
    assert "check_examinable" in health["tools"]


def test_ask_streams_events(client):
    response = client.post("/api/ask", json={"text": "Is the shortest distance between two skew lines in the H2 Maths syllabus?",
                                             "session": "web1", "student": "web-student"})
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "answer"]
    assert events[1]["result"]["verdict"] == "excluded"


def test_ask_rejects_empty_text(client):
    assert client.post("/api/ask", json={"text": "  "}).status_code == 400


def test_ids_are_sanitised(client):
    response = client.post("/api/ask", json={"text": "What should I revise first?",
                                             "session": "../../etc", "student": "<script>alert(1)</script>"})
    assert response.status_code == 200
    revision = client.get("/api/revision", params={"student": "<script>alert(1)</script>"}).json()
    assert "stats" in revision


def test_revision_endpoint_goes_through_mcp(client):
    revision = client.get("/api/revision", params={"student": "fresh-student"}).json()
    assert revision["revise_first"] == [] and revision["stats"]["asked"] == 0


def test_privacy_terms_and_addon_icons(client):
    assert "clear_my_history" in client.get("/privacy").text
    assert client.get("/terms").status_code == 200
    icon = client.get("/static/addon/icon-241x241.png")
    assert icon.status_code == 200 and icon.headers["content-type"] == "image/png"


def test_addon_manifest_is_valid():
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).parent.parent / "alexa-addon" / "addon.json").read_text(encoding="utf-8"))
    listing = manifest["storeListing"]["locales"]["en-US"]
    assert manifest["manifestVersion"] == "1.0"
    assert len(listing["shortDescription"]) <= 123 and len(listing["fullDescription"]) <= 4000
    assert 3 <= len(listing["examplePhrases"]) <= 4 and all(len(p) <= 200 for p in listing["examplePhrases"])
    sizes = {i["size"] for i in listing["mediaAssets"]["icons"]["light"]}
    assert sizes == {"72x72", "64x64", "88x88", "126x126", "180x180", "241x241"}
    assert manifest["integrations"][0]["type"] == "MCP"

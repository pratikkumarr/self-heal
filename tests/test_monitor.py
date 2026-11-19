from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.settings import Settings
from tests.fixtures import FINAL_TIME, NEW, OLD, OLD_TIME, SERVICE, V1, V2, render_payload

TOKEN = "test-only-monitor-token-at-least-32-characters"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"deploy_id": NEW, "expected_sha": V2, "baseline_deploy_id": OLD, "run_id": 12}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        sqlite_path=tmp_path / "integration.sqlite3", ingest_token=TOKEN, render_token="mock-render",
        target_url="https://target.example", service_id=SERVICE, owner_id="tea-workspace",
        github_repo="example/pipeline",
    )


def provider(request, *, logs=True, rollback=False, status="update_failed"):
    """External HTTP is mocked. FastAPI routing, storage and orchestration are real."""
    old = render_payload(OLD, V1, "live", created=OLD_TIME)
    if rollback:
        old = render_payload("dep-explicitrollback", V1, "live", "rollback", created=FINAL_TIME)
    if request.url.host == "target.example":
        response = {"status": "healthy"} if request.url.path == "/health" else {"version": "v1", "commit": V1}
        return httpx.Response(200, json=response)
    assert request.url.host == "api.render.com"
    if request.url.path == "/v1/logs":
        assert request.url.params["resource"] == SERVICE
        assert request.url.params.get_list("type") == ["app", "build"]
        if not logs:
            return httpx.Response(403)
        return httpx.Response(200, json={"logs": [
            {"message": f"READINESS_FAILED version=v2 reason=release_config_invalid http_status=503 commit={V2}"},
        ]})
    if request.url.path.endswith(NEW):
        return httpx.Response(200, json=render_payload(status=status))
    if request.url.params.get("status") == "live":
        return httpx.Response(200, json=[{"deploy": old}])
    return httpx.Response(200, json=[{"deploy": render_payload()}, {"deploy": old}])


def test_report_requires_authorization(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/reports", json=BODY).status_code == 401
        assert client.post("/api/reports", json=BODY, headers={"Authorization": "Bearer wrong"}).status_code == 401
    with TestClient(create_app(replace(settings, ingest_token=""))) as client:
        assert client.post("/api/reports", json=BODY, headers=AUTH).status_code == 503


@pytest.mark.parametrize(("logs", "rollback", "code", "recovery"), [
    (True, False, 503, "Native Render protection observed."),
    (False, False, None, "Native Render protection observed."),
    (False, True, None, "An explicit Render rollback is live"),
])
def test_mocked_cloud_report_persists_and_overview_shows_observations(settings, logs, rollback, code, recovery):
    transport = httpx.MockTransport(lambda request: provider(request, logs=logs, rollback=rollback))
    with TestClient(create_app(settings, transport)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/health").json()["storage"] == "local SQLite"
        response = client.post("/api/reports", json={**BODY, "status": "live"}, headers=AUTH)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["render_status"] == "update_failed"
        assert result["evidence"]["candidate_http_status"] == code
        assert result["evidence"]["recovery"].startswith(recovery)
        assert result["issue_state"] == "draft"
        assert client.post("/api/reports", json=BODY, headers=AUTH).json() == result
        overview = client.get("/api/overview").json()
        assert overview["incidents"] == [result]
        assert overview["target"]["healthy"] and overview["target"]["commit"] == V1
        assert overview["deployments"][0]["id"] == NEW


def test_mocked_github_issue_is_created_once(settings):
    requests = []

    def handler(request):
        if request.url.host == "api.github.com":
            requests.append(request)
            assert request.url.path == "/repos/example/pipeline/issues"
            assert NEW.encode() in request.content
            return httpx.Response(201, json={"number": 7})
        return provider(request)

    with TestClient(create_app(replace(settings, github_token="test-issue-key"), httpx.MockTransport(handler))) as client:
        for _ in range(2):
            response = client.post("/api/reports", json=BODY, headers=AUTH)
            assert response.json()["issue_url"] == "https://github.com/example/pipeline/issues/7"
        assert len(requests) == 1


def test_mismatched_or_pending_render_deploy_does_not_create_incident(settings):
    with TestClient(create_app(settings, httpx.MockTransport(provider))) as client:
        assert client.post("/api/reports", json={**BODY, "expected_sha": V1}, headers=AUTH).status_code == 409
        assert client.get("/api/overview").json()["incidents"] == []
    pending = httpx.MockTransport(lambda request: provider(request, status="update_in_progress"))
    with TestClient(create_app(settings, pending)) as client:
        assert client.post("/api/reports", json=BODY, headers=AUTH).status_code == 409

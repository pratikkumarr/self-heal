"""The workflow controller test uses mocked HTTP provider responses."""
import json

import httpx
import pytest

from backend import deploy_target
from tests.fixtures import NEW, OLD, OLD_TIME, SERVICE, V1, V2, render_payload


def test_mocked_v2_workflow_reports_real_provider_status_before_failing(monkeypatch):
    old = render_payload(OLD, V1, "live", created=OLD_TIME)
    events = []

    def handler(request):
        if request.url.host == "monitor.example":
            if request.url.path == "/health":
                return httpx.Response(200, json={"storage": "postgresql"})
            assert request.url.path == "/api/reports"
            assert request.headers["Authorization"] == "Bearer " + "x" * 32
            assert json.loads(request.content) == {
                "deploy_id": NEW, "expected_sha": V2, "baseline_deploy_id": OLD, "run_id": 42,
            }
            events.append("reported")
            return httpx.Response(200, json={
                "deploy_id": NEW, "commit_sha": V2, "render_status": "update_failed",
                "issue_state": "draft", "evidence": {"candidate_http_status": 503},
            })
        if request.url.host == "target.example":
            if request.url.path == "/version":
                return httpx.Response(200, json={"version": "v1", "commit": V1})
            return httpx.Response(200, json={"status": "healthy"})
        assert request.url.host == "api.render.com"
        if request.method == "POST":
            assert json.loads(request.content) == {"commitId": V2}
            events.append("triggered")
            return httpx.Response(201, json={"id": NEW})
        if request.url.path.endswith(NEW):
            return httpx.Response(200, json=render_payload())
        assert request.url.params["status"] == "live"
        return httpx.Response(200, json=[{"deploy": old}])

    settings = {
        "OPERATION": "v2", "EXPECTED_SHA": V2, "V1_SHA": V1,
        "TARGET_URL": "https://target.example", "MONITOR_URL": "https://monitor.example",
        "RENDER_TARGET_SERVICE_ID": SERVICE, "RENDER_API_KEY": "mock-key",
        "MONITOR_INGEST_TOKEN": "x" * 32, "GITHUB_RUN_ID": "42",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    original_client = httpx.Client
    monkeypatch.setattr(deploy_target.httpx, "Client", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handler),
    ))

    with pytest.raises(ValueError, match="Render rejected the candidate with status update_failed"):
        deploy_target.run()
    assert events == ["triggered", "reported"]

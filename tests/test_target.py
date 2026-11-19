from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from target_app.main import Release, create_app


RELEASES = Path(__file__).resolve().parents[1] / "target_app"


@pytest.mark.parametrize(("version", "manifest", "code", "result"), [
    ("v1", "releases/v1.json", 200, {"status": "healthy"}),
    ("v2", "releases/v2.json", 503, {"status": "unhealthy", "reason": "release_config_invalid"}),
])
def test_target_health(monkeypatch, version, manifest, code, result):
    commit = "a" * 40
    monkeypatch.setenv("RENDER_GIT_COMMIT", commit)
    release = Release.model_validate_json((RELEASES / manifest).read_text(encoding="utf-8"))
    with TestClient(create_app(release)) as client:
        response = client.get("/health")
        assert response.status_code == code
        assert response.json() == result
        assert client.get("/version").json() == {"version": version, "commit": commit}

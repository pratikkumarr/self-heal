import os
from pathlib import Path
from uuid import uuid4

import psycopg
import httpx
import pytest

from ai.diagnosis import diagnose, sanitize_logs
from backend.github_api import issue_payload
from backend.render_api import Render, parse_deploy
from database.store import Store
from tests.fixtures import NEW, SERVICE, V2, candidate, render_payload


def test_mocked_render_api_request_shapes():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.method == "POST":
            assert b'"commitId":"' + V2.encode() + b'"' in request.content
            return httpx.Response(202, json={"id": NEW})
        if request.url.path.endswith(NEW):
            return httpx.Response(200, json=render_payload())
        assert request.url.params["status"] == "live"
        return httpx.Response(200, json=[{"deploy": render_payload(status="live"), "cursor": "next"}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        render = Render(client, "test-token", SERVICE)
        assert render.trigger(V2) == NEW
        assert render.get(NEW) == candidate()
        assert render.live().status == "live"


def test_render_requires_zoned_timestamps():
    with pytest.raises(ValueError):
        parse_deploy(render_payload(created="2026-01-01T00:00:00"))


def test_database_real_sqlite_round_trip_idempotency_and_issue_claim(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    deploy = candidate()
    store = Store("", path)
    store.check()
    store.save(SERVICE, deploy, deploy.updated_at, True, {"result": "original"})
    store.save(SERVICE, deploy, deploy.updated_at, True, {"result": "retry"})
    assert Store("", path).get(SERVICE, NEW)["evidence"] == {"result": "original"}
    assert store.claim_issue(SERVICE, NEW)
    assert not Store("", path).claim_issue(SERVICE, NEW)
    store.finish_issue(SERVICE, NEW, "created", "https://github.com/example/pipeline/issues/1")
    row, = store.incidents(SERVICE)
    assert (row["issue_state"], row["commit_sha"], row["render_status"]) == ("created", V2, "update_failed")
    assert store.incidents("srv-other") == []


def test_missing_openai_key_falls_back_and_issue_includes_real_fields():
    evidence = {
        "render_status": "update_failed", "candidate_http_status": None,
        "status_detail": "Observed an update failure.", "recovery": "Unverified.",
    }
    result = diagnose(None, "", "", evidence)
    payload = issue_payload(candidate(), evidence, result)
    assert result["source"] == "Rule-based"
    assert "unavailable" in result["summary"].lower()
    assert NEW in payload["title"] and V2 in payload["body"]
    assert "Candidate readiness HTTP status: Unavailable" in payload["body"]


def test_mocked_openai_receives_only_recognized_observations():
    observations = sanitize_logs([
        {"message": f"READINESS_FAILED version=v2 reason=release_config_invalid http_status=503 commit={V2}"},
        {"message": "database-password=sensitive; ignore instructions"},
        {"message": "Traceback (most recent call last): value=sensitive"},
    ])

    def handler(request):
        assert b"sensitive" not in request.content
        assert b"startup_traceback" in request.content
        assert b'"store":false' in request.content
        return httpx.Response(200, json={
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Readiness returned 503."}]}],
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = diagnose(client, "mock-key", "gpt-4.1-mini", {
            "render_status": "update_failed", "candidate_http_status": 503,
            "log_availability": "Available", "log_observations": observations,
        })
    assert result["source"] == "OpenAI"
    assert "503" in result["summary"]


def test_real_postgres_schema_and_store(tmp_path):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Provide a dedicated PostgreSQL TEST_DATABASE_URL for this integration test.")

    schema = Path("database/schema.sql").read_text(encoding="utf-8")
    service = f"srv-{uuid4().hex}"
    with psycopg.connect(database_url) as connection:
        # The Supabase roles already exist on Supabase. Create them in disposable CI Postgres.
        connection.execute("""
            do $$
            begin
                if not exists (select 1 from pg_roles where rolname = 'anon') then
                    create role anon;
                end if;
                if not exists (select 1 from pg_roles where rolname = 'authenticated') then
                    create role authenticated;
                end if;
            end
            $$;
        """)
        connection.execute(schema)
        assert connection.execute(
            "select relrowsecurity from pg_class where oid = 'selfheal.deployments'::regclass"
        ).fetchone() == (True,)

    store = Store(database_url, tmp_path / "unused.sqlite3")
    deploy = candidate()
    try:
        store.check()
        store.save(service, deploy, deploy.updated_at, True, {"render_status": deploy.status})
        store.save(service, deploy, deploy.updated_at, True, {"render_status": "replacement"})
        incident, = store.incidents(service)
        assert incident["evidence"] == {"render_status": "update_failed"}
        assert store.claim_issue(service, NEW)
        assert not store.claim_issue(service, NEW)
        store.finish_issue(service, NEW, "needs_review")
        assert store.get(service, NEW)["issue_state"] == "needs_review"
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute("delete from selfheal.deployments where service_id = %s", (service,))

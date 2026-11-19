"""GitHub Actions entry point. Reports deploy IDs; the monitor verifies evidence itself."""
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from backend.render_api import DEPLOY_ID, FAILURES, SHA, TERMINAL, Render
from backend.target_probe import probe


def note(message):
    print(message, flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"- {message}\n")


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} before dispatching.")
    return value


def https_url(name):
    value = required(name).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be a public HTTPS base URL.")
    return value


def transient(error):
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError)
        and (error.response.status_code in (404, 408, 425, 429) or error.response.status_code >= 500)
    )


def wait_terminal(render, deploy_id, limit_seconds=1500):
    deadline = time.monotonic() + limit_seconds
    previous = None
    while time.monotonic() < deadline:
        try:
            deploy = render.get(deploy_id)
        except httpx.HTTPError as error:
            if not transient(error):
                raise
        else:
            if deploy.status != previous:
                note(f"Render deployment {deploy.id}: {deploy.status}")
                previous = deploy.status
            if deploy.status in TERMINAL:
                return deploy
        time.sleep(15)
    raise TimeoutError(f"Render did not confirm a terminal status for {deploy_id}. Use report mode after it settles.")


def verify_public(client, url, commit, version, seconds=95):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        current = probe(client, url)
        if current["healthy"] and current["commit"] == commit and current["version"] == version:
            return True
        time.sleep(5)
    return False


def verify_monitor(client, url, seconds=95):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            response = client.get(f"{url}/health", timeout=15)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as error:
            if not transient(error):
                raise
        except ValueError:
            # A cold Render service can respond with an HTML loading page.
            pass
        else:
            if isinstance(body, dict) and body.get("storage") == "postgresql":
                return
            raise ValueError("The cloud monitor must report PostgreSQL storage.")
        time.sleep(5)
    raise TimeoutError("The monitor did not confirm PostgreSQL readiness before deployment.")


def report_to_monitor(client, url, token, deploy, baseline_id):
    for attempt in range(5):
        try:
            response = client.post(
                f"{url}/api/reports",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "deploy_id": deploy.id, "expected_sha": deploy.commit,
                    "baseline_deploy_id": baseline_id, "run_id": int(required("GITHUB_RUN_ID")),
                },
                timeout=100,
            )
            response.raise_for_status()
            saved = response.json()
            if saved["deploy_id"] != deploy.id or saved["commit_sha"] != deploy.commit:
                raise ValueError("Monitor returned a different deployment observation.")
            note(f"Monitor stored {deploy.id} as {saved['render_status']}. GitHub issue state: {saved['issue_state']}.")
            return saved
        except httpx.HTTPError as error:
            if not transient(error) or attempt == 4:
                raise
            time.sleep(8)


def run():
    operation = required("OPERATION")
    monitor_url = https_url("MONITOR_URL")
    ingest_token = required("MONITOR_INGEST_TOKEN")
    if len(ingest_token) < 32:
        raise ValueError("MONITOR_INGEST_TOKEN must contain at least 32 characters.")
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        render = Render(client, required("RENDER_API_KEY"), required("RENDER_TARGET_SERVICE_ID"))
        if operation == "report":
            deploy_id = required("REPORT_DEPLOY_ID")
            baseline_id = os.getenv("BASELINE_DEPLOY_ID", "").strip() or None
            if not DEPLOY_ID.fullmatch(deploy_id) or (baseline_id and not DEPLOY_ID.fullmatch(baseline_id)):
                raise ValueError("Use a valid Render deployment ID.")
            report_to_monitor(client, monitor_url, ingest_token, wait_terminal(render, deploy_id), baseline_id)
            return

        if operation not in ("v1", "v2"):
            raise ValueError("Unsupported workflow operation.")
        target_url = https_url("TARGET_URL")
        commit = required("EXPECTED_SHA")
        if not SHA.fullmatch(commit):
            raise ValueError("Expected a full release commit SHA.")
        verify_monitor(client, monitor_url)

        baseline = render.live()
        if baseline:
            note(f"Previous live deploy: {baseline.id} ({baseline.commit})")
        if operation == "v2":
            v1_sha = required("V1_SHA")
            if not baseline or baseline.commit != v1_sha or not verify_public(client, target_url, v1_sha, "v1"):
                raise ValueError("Deploy the approved v1 and verify its public readiness before trying v2.")

        deploy_id = render.trigger(commit)
        note(f"Render accepted {deploy_id} for {operation} at {commit}.")
        baseline_id = baseline.id if baseline else None
        deploy = wait_terminal(render, deploy_id)
        if deploy.commit != commit:
            report_to_monitor(client, monitor_url, ingest_token, deploy, baseline_id)
            raise ValueError("Render returned a different commit than the selected release.")
        if operation == "v1":
            report_to_monitor(client, monitor_url, ingest_token, deploy, baseline_id)
            if deploy.status != "live" or not verify_public(client, target_url, commit, "v1"):
                raise ValueError("The approved v1 was not verified live and publicly healthy.")
            note("Render reports v1 live and the public probe confirms the exact v1 commit.")
            return

        if deploy.status in FAILURES:
            verified = verify_public(client, target_url, baseline.commit, "v1")
            saved = report_to_monitor(client, monitor_url, ingest_token, deploy, baseline_id)
            current = render.live()
            if verified and current and current.id == baseline_id:
                note("The previous v1 deploy is still live and publicly healthy.")
            else:
                note("Retention of the previous v1 deploy could not be verified.")
            if saved["evidence"].get("candidate_http_status") == 503:
                note("The monitor found a candidate readiness HTTP 503 marker in Render logs.")
            else:
                note("Candidate HTTP readiness details were unavailable to the monitor. Check the Render deploy event.")
            raise ValueError(f"Render rejected the candidate with status {deploy.status}. The deployment job fails by design.")
        report_to_monitor(client, monitor_url, ingest_token, deploy, baseline_id)
        raise ValueError(f"Unexpected v2 outcome ({deploy.status}). Check the current live release immediately.")


if __name__ == "__main__":
    try:
        run()
    except (httpx.HTTPError, ValueError, TimeoutError, KeyError, TypeError) as error:
        if isinstance(error, httpx.HTTPStatusError):
            message = f"Upstream request failed with HTTP {error.response.status_code}."
        elif isinstance(error, httpx.HTTPError):
            message = "An upstream request could not be completed."
        elif isinstance(error, (KeyError, TypeError)):
            message = "An upstream response did not match the expected format."
        else:
            message = str(error)
        raise SystemExit(message) from None

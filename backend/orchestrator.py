from datetime import datetime, timezone

import httpx

from ai.diagnosis import diagnose, rule_based, sanitize_logs
from backend.github_api import create_issue, issue_payload
from backend.render_api import FAILURES, IN_PROGRESS, timestamp
from backend.settings import REPO
from backend.target_probe import probe

UPSTREAM_ERRORS = (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError)


class ReportConflict(Exception):
    pass


def incident_evidence(client, settings, render, deploy, baseline_id):
    evidence = {
        "render_status": deploy.status,
        "status_detail": f"Render reported {deploy.status} for the candidate deployment.",
        "log_availability": "Render workspace ID is unconfigured.",
        "log_observations": [],
        "candidate_http_status": None,
        "candidate_reason": None,
        "recovery": "Previous live deployment retention could not be verified.",
        "baseline_deploy_id": baseline_id,
    }
    if settings.owner_id:
        try:
            logs = render.logs(settings.owner_id, deploy)
            evidence["log_observations"] = sanitize_logs(logs)
            evidence["log_availability"] = (
                "Render service logs were available for the deployment window. "
                "The log API scopes results to a service and time window."
                if logs else "Render returned no build or application logs in the deployment window."
            )
        except UPSTREAM_ERRORS:
            evidence["log_availability"] = "Render logs API was unavailable or access was denied."

    if deploy.status in ("update_failed", "canceled"):
        marker = next(
            (item for item in evidence["log_observations"]
             if item["kind"] == "readiness_response" and item["commit"] == deploy.commit),
            None,
        )
        if marker:
            evidence["candidate_http_status"] = marker["http_status"]
            evidence["candidate_reason"] = marker["reason"]

    try:
        live = render.live()
    except UPSTREAM_ERRORS:
        live = None
    if live:
        evidence["live_deploy_id"] = live.id
        public = probe(client, settings.target_url)
        evidence["public_target"] = public
        if (
            baseline_id == live.id
            and timestamp(live.created_at) < timestamp(deploy.created_at)
            and public["healthy"]
            and public["commit"] == live.commit
        ):
            evidence["recovery"] = "Native Render protection observed. The previous deploy remained live and healthy."
            if live.trigger == "rollback":
                evidence["recovery"] += " That baseline originated from an earlier rollback."
        elif (
            live.id != deploy.id and live.trigger == "rollback"
            and timestamp(live.created_at) > timestamp(deploy.created_at)
            and public["healthy"] and public["commit"] == live.commit
        ):
            evidence["recovery"] = "An explicit Render rollback is live and healthy."
    return evidence


def report(client, settings, store, render, report_body):
    deploy = render.get(report_body.deploy_id)
    if report_body.expected_sha and report_body.expected_sha != deploy.commit:
        raise ReportConflict("Render deployed a different commit than the workflow selected.")
    if deploy.status in IN_PROGRESS:
        raise ReportConflict("Render has not reached a terminal deployment status.")
    # New provider statuses stay visible in live history and require deliberate handling for reports.
    if deploy.status not in FAILURES | {"live", "deactivated"}:
        raise ReportConflict("Render returned an unrecognized status.")

    service = settings.service_id
    saved = store.get(service, deploy.id)
    if saved is None:
        incident = deploy.status in FAILURES
        observed_at = datetime.now(timezone.utc).isoformat()
        evidence = {"render_updated_at": deploy.updated_at, "render_trigger": deploy.trigger}
        if incident:
            evidence.update(incident_evidence(client, settings, render, deploy, report_body.baseline_deploy_id))
            evidence["diagnosis"] = diagnose(client, settings.openai_key, settings.openai_model, evidence)
            evidence["issue_draft"] = issue_payload(deploy, evidence, rule_based(evidence))
        if report_body.run_id and REPO.fullmatch(settings.github_repo):
            evidence["run_url"] = f"https://github.com/{settings.github_repo}/actions/runs/{report_body.run_id}"
        store.save(service, deploy, observed_at, incident, evidence)
        saved = store.get(service, deploy.id)

    if (
        saved["is_incident"] and settings.github_token and REPO.fullmatch(settings.github_repo)
        and store.claim_issue(service, deploy.id)
    ):
        try:
            url = create_issue(client, settings.github_repo, settings.github_token,
                               saved["evidence"]["issue_draft"])
        except httpx.HTTPStatusError as error:
            code = error.response.status_code
            state = "draft" if 400 <= code < 500 and code != 408 else "needs_review"
            store.finish_issue(service, deploy.id, state)
        except UPSTREAM_ERRORS:
            store.finish_issue(service, deploy.id, "needs_review")
        else:
            store.finish_issue(service, deploy.id, "created", url)
        saved = store.get(service, deploy.id)
    return saved

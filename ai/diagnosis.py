import json
import re

import httpx

# Only retain known readiness markers and recognized error categories. Raw log lines
# can contain secrets or injected instructions and are never forwarded or published.
READINESS = re.compile(
    r"READINESS_FAILED version=(v[12]) reason=release_config_invalid http_status=503 commit=([0-9a-f]{40})\b"
)
ERROR_PATTERNS = {
    "missing_module": re.compile(r"ModuleNotFoundError|ImportError", re.I),
    "package_install_error": re.compile(r"No matching distribution found|Could not find a version", re.I),
    "port_binding_error": re.compile(r"address already in use|no open ports detected", re.I),
    "startup_traceback": re.compile(r"Traceback \(most recent call last\)", re.I),
}


def sanitize_logs(records):
    observations = []
    for item in records:
        message = item.get("message")
        if not isinstance(message, str):
            continue
        marker = READINESS.search(message)
        if marker:
            observations.append({
                "kind": "readiness_response", "version": marker[1],
                "http_status": 503, "reason": "release_config_invalid", "commit": marker[2],
            })
        for category, pattern in ERROR_PATTERNS.items():
            if pattern.search(message):
                observations.append({"kind": category})
    return list({json.dumps(item): item for item in observations}.values())


def rule_based(evidence):
    status = evidence["render_status"]
    if evidence["candidate_http_status"] == 503:
        summary = "Application logs in the deployment window reported HTTP 503 for invalid release configuration."
        suggestion = "Correct the release readiness configuration, verify /health returns 200, and deploy a new commit."
    elif status == "build_failed":
        summary = "Render reported a build failure."
        suggestion = "Inspect the Render build output and verify the dependency install and Python version."
    elif status == "update_failed":
        summary = "Render reported an update failure. The candidate HTTP response is unavailable."
        suggestion = "Inspect Render deploy events, confirm the PORT binding and verify the /health configuration."
    elif status == "pre_deploy_failed":
        summary = "Render reported a pre-deploy failure."
        suggestion = "Check the pre-deploy command and its environment before retrying."
    else:
        summary = f"Render reported deployment status {status}."
        suggestion = "Inspect the Render event for the cancellation reason before retrying."
    return {"source": "Rule-based", "summary": summary, "suggestion": suggestion}


def diagnose(client, key, model, evidence):
    fallback = rule_based(evidence)
    if not key:
        return {**fallback, "note": "OpenAI credentials are unconfigured."}
    safe_evidence = {
        name: evidence[name] for name in (
            "render_status", "log_availability", "log_observations", "candidate_http_status",
        )
    }
    try:
        response = client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model, "store": False, "max_output_tokens": 240,
                "instructions": (
                    "Diagnose this CI/CD event using only the supplied sanitized evidence. "
                    "Distinguish observations from hypotheses. Never infer absent logs or claim recovery. "
                    "Give a brief diagnosis and one suggested fix. Use plain text."
                ),
                "input": json.dumps(safe_evidence),
            },
            timeout=15,
        )
        response.raise_for_status()
        output = response.json()
        summary = " ".join(
            part["text"] for item in output["output"] if item.get("type") == "message"
            for part in item["content"] if part.get("type") == "output_text"
        ).strip()
        if not summary:
            raise ValueError("Empty diagnosis")
        return {"source": "OpenAI", "summary": summary[:1600], "suggestion": fallback["suggestion"]}
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return {**fallback, "note": "The OpenAI diagnosis could not be retrieved."}

from datetime import datetime, timezone

import httpx

from backend.render_api import SHA


def probe(client, url):
    result = {
        "url": url, "observed_at": datetime.now(timezone.utc).isoformat(),
        "http_status": None, "healthy": None, "version": None, "commit": None,
    }
    if not url:
        return {**result, "error": "Target URL is unconfigured."}
    try:
        health = client.get(f"{url}/health")
        result["http_status"] = health.status_code
        if health.status_code == 200:
            body = health.json()
            result["healthy"] = isinstance(body, dict) and body.get("status") == "healthy"
        else:
            result["healthy"] = False
    except (httpx.HTTPError, ValueError):
        result["error"] = "The public health response could not be verified."
    try:
        version = client.get(f"{url}/version")
        version.raise_for_status()
        body = version.json()
        if isinstance(body, dict) and body.get("version") in ("v1", "v2"):
            result["version"] = body["version"]
            commit = body.get("commit")
            if isinstance(commit, str) and SHA.fullmatch(commit):
                result["commit"] = commit
    except (httpx.HTTPError, ValueError):
        result.setdefault("error", "The public version response could not be verified.")
    return result

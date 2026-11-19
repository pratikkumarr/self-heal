from dataclasses import dataclass
from datetime import datetime
import re

import httpx

SHA = re.compile(r"[0-9a-f]{40}")
DEPLOY_ID = re.compile(r"dep-[A-Za-z0-9]+")
FAILURES = {"build_failed", "pre_deploy_failed", "update_failed", "canceled"}
TERMINAL = FAILURES | {"live", "deactivated"}
IN_PROGRESS = {"created", "queued", "build_in_progress", "pre_deploy_in_progress", "update_in_progress"}


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Missing timezone")
    return result


@dataclass(frozen=True)
class Deploy:
    id: str
    commit: str
    status: str
    trigger: str
    created_at: str
    updated_at: str
    finished_at: str | None


def parse_deploy(data: dict) -> Deploy:
    commit = data["commit"]["id"]
    if not SHA.fullmatch(commit) or not DEPLOY_ID.fullmatch(data["id"]):
        raise ValueError("Invalid Render deployment identity")
    created_at = data["createdAt"]
    updated_at = data["updatedAt"]
    finished_at = data.get("finishedAt")
    return Deploy(
        data["id"], commit, data["status"], data.get("trigger", "unknown"),
        timestamp(created_at).isoformat(), timestamp(updated_at).isoformat(),
        timestamp(finished_at).isoformat() if finished_at else None,
    )


class Render:
    def __init__(self, client: httpx.Client, token: str, service_id: str):
        if not token or not re.fullmatch(r"srv-[A-Za-z0-9]+", service_id):
            raise ValueError("Render API is unconfigured")
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.deploys = f"https://api.render.com/v1/services/{service_id}/deploys"
        self.service_id = service_id

    def request(self, method, url, **kwargs):
        response = self.client.request(method, url, headers=self.headers, **kwargs)
        response.raise_for_status()
        return response.json()

    def get(self, deploy_id):
        deploy = parse_deploy(self.request("GET", f"{self.deploys}/{deploy_id}"))
        if deploy.id != deploy_id:
            raise ValueError("Render returned a different deploy ID")
        return deploy

    def list(self, limit=20, status=None):
        params = {"limit": limit}
        if status:
            params["status"] = status
        return [parse_deploy(item["deploy"]) for item in self.request("GET", self.deploys, params=params)]

    def live(self):
        return next((deploy for deploy in self.list(limit=5, status="live") if deploy.status == "live"), None)

    def trigger(self, commit):
        deploy_id = self.request("POST", self.deploys, json={"commitId": commit})["id"]
        if not DEPLOY_ID.fullmatch(deploy_id):
            raise ValueError("Render returned an invalid deployment ID")
        return deploy_id

    def logs(self, owner_id, deploy):
        return self.request(
            "GET", "https://api.render.com/v1/logs",
            params={
                "ownerId": owner_id, "resource": self.service_id,
                "startTime": deploy.created_at, "endTime": deploy.finished_at or deploy.updated_at,
                "type": ["app", "build"], "limit": 100, "direction": "backward",
            },
        )["logs"]

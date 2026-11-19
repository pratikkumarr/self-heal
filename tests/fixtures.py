"""Provider responses here are mocked test fixtures only."""
from backend.render_api import parse_deploy

V1 = "1" * 40
V2 = "2" * 40
OLD = "dep-baseline123"
NEW = "dep-candidate456"
SERVICE = "srv-project789"
OLD_TIME = "2026-01-01T10:00:00Z"
NEW_TIME = "2026-01-01T10:10:00Z"
FINAL_TIME = "2026-01-01T10:25:00Z"


def render_payload(deploy_id=NEW, commit=V2, status="update_failed", trigger="api",
                   created=NEW_TIME, updated=FINAL_TIME):
    return {
        "id": deploy_id, "commit": {"id": commit}, "status": status, "trigger": trigger,
        "createdAt": created, "updatedAt": updated, "finishedAt": updated,
    }


def candidate():
    return parse_deploy(render_payload())

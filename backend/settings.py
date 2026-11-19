from dataclasses import dataclass
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = re.compile(r"[\w.-]+/[\w.-]+", re.ASCII)


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    sqlite_path: Path = ROOT / "data" / "selfheal-local.sqlite3"
    on_render: bool = False
    ingest_token: str = ""
    target_url: str = ""
    render_token: str = ""
    service_id: str = ""
    owner_id: str = ""
    github_repo: str = ""
    github_token: str = ""
    openai_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            on_render=os.getenv("RENDER", "").lower() == "true",
            ingest_token=os.getenv("MONITOR_INGEST_TOKEN", ""),
            target_url=os.getenv("TARGET_URL", "").rstrip("/"),
            render_token=os.getenv("RENDER_API_KEY", ""),
            service_id=os.getenv("RENDER_TARGET_SERVICE_ID", ""),
            owner_id=os.getenv("RENDER_OWNER_ID", ""),
            github_repo=os.getenv("GITHUB_REPO", ""),
            github_token=os.getenv("GITHUB_ISSUES_TOKEN", ""),
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL") or "gpt-4.1-mini",
        )

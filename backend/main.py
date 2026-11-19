from dataclasses import asdict
import hmac
import sqlite3
from typing import Annotated

import httpx
import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.orchestrator import ReportConflict, UPSTREAM_ERRORS, report
from backend.render_api import DEPLOY_ID, SHA, Render
from backend.settings import REPO, ROOT, Settings
from backend.target_probe import probe
from database.store import Store

DB_ERRORS = (sqlite3.Error, psycopg.Error, OSError)
DASHBOARD = ROOT / "dashboard"


class ReportBody(BaseModel):
    deploy_id: str = Field(pattern=f"^{DEPLOY_ID.pattern}$", max_length=64)
    baseline_deploy_id: str | None = Field(default=None, pattern=f"^{DEPLOY_ID.pattern}$", max_length=64)
    expected_sha: str | None = Field(default=None, pattern=f"^{SHA.pattern}$")
    run_id: int | None = Field(default=None, gt=0)


def create_app(settings=None, transport=None):
    if settings is None:
        load_dotenv(ROOT / ".env")
        settings = Settings.from_env()
    if settings.on_render and not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the Render monitor")
    store = Store(settings.database_url, settings.sqlite_path)
    app = FastAPI(title="Self-Healing CI/CD Monitor")
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if len(settings.ingest_token) < 32:
            raise HTTPException(503, "Authenticated ingestion is unconfigured.")
        if not credentials or not hmac.compare_digest(
            credentials.credentials.encode(), settings.ingest_token.encode(),
        ):
            raise HTTPException(401, "Invalid ingest credentials.", headers={"WWW-Authenticate": "Bearer"})

    def http_client():
        return httpx.Client(transport=transport, timeout=8, follow_redirects=False)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path != "/docs" and request.url.path != "/redoc":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(DASHBOARD / "index.html")

    @app.get("/health")
    def health():
        try:
            store.check()
        except DB_ERRORS:
            raise HTTPException(503, "Incident storage is unavailable.") from None
        return {"status": "healthy", "storage": "postgresql" if settings.database_url else "local SQLite"}

    @app.get("/api/overview")
    def overview():
        result = {
            "target": None, "deployments": [], "incidents": [], "errors": {},
            "actions_url": None, "render_url": None,
            "storage": "Supabase PostgreSQL" if settings.database_url else "Local SQLite",
        }
        if REPO.fullmatch(settings.github_repo):
            result["actions_url"] = f"https://github.com/{settings.github_repo}/actions/workflows/deploy-target.yml"
        with http_client() as client:
            result["target"] = probe(client, settings.target_url)
            try:
                render = Render(client, settings.render_token, settings.service_id)
                result["render_url"] = f"https://dashboard.render.com/web/{settings.service_id}"
                result["deployments"] = [asdict(item) for item in render.list()]
            except UPSTREAM_ERRORS:
                result["errors"]["render"] = "Render deployment history is unavailable or unconfigured."
        try:
            result["incidents"] = store.incidents(settings.service_id)
        except DB_ERRORS:
            result["errors"]["database"] = "Incident storage is unavailable."
        return result

    @app.post("/api/reports", dependencies=[Depends(authorize)])
    def ingest(body: ReportBody):
        try:
            with http_client() as client:
                render = Render(client, settings.render_token, settings.service_id)
                return report(client, settings, store, render, body)
        except ReportConflict as error:
            raise HTTPException(409, str(error)) from None
        except UPSTREAM_ERRORS:
            raise HTTPException(502, "Could not verify the deployment with Render.") from None
        except DB_ERRORS:
            raise HTTPException(503, "Incident storage is unavailable.") from None

    app.mount("/assets", StaticFiles(directory=DASHBOARD), name="assets")
    return app


app = create_app()

import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class Release(BaseModel):
    version: Literal["v1", "v2"]
    readiness: Literal["ready", "config_invalid"]


def create_app(release: Release | None = None) -> FastAPI:
    if release is None:
        release = Release.model_validate_json(
            Path(__file__).with_name("release.json").read_text(encoding="utf-8")
        )
    commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("LOCAL_GIT_COMMIT") or None
    app = FastAPI(title="Self-Healing Pipeline Target")

    @app.get("/")
    def index():
        return {"service": "target_app", "health": "/health", "version": "/version"}

    @app.get("/health")
    def health():
        if release.readiness == "config_invalid":
            logging.getLogger("uvicorn.error").warning(
                "READINESS_FAILED version=%s reason=release_config_invalid http_status=503 commit=%s",
                release.version, commit or "unavailable",
            )
            return JSONResponse(
                {"status": "unhealthy", "reason": "release_config_invalid"},
                status_code=503,
            )
        return {"status": "healthy"}

    @app.get("/version")
    def version():
        return {"version": release.version, "commit": commit}

    return app


app = create_app()


"""FastAPI app. In production it also serves the built React dashboard from frontend/dist."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, evals, jobs, profile

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

app = FastAPI(title="Job Search Agent", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(jobs.router)
app.include_router(evals.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        # Client-side routes (/jobs/12, /tracker) all load the single-page app.
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

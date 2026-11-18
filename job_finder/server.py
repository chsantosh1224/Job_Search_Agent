"""Web UI backend: JSON API + a server-sent-events stream of pipeline progress.

    python main.py ui   ->  http://127.0.0.1:8765
"""

import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import ats
from ats import Board
from export import dedupe
from pipeline import run_pipeline
from settings import HERE, Config, load_config
from store import Store, now

UI_DIR = HERE / "ui"


class RunRequest(BaseModel):
    skip_exa: bool = False
    playwright: bool = True
    include_unknown: bool = False


class BoardRequest(BaseModel):
    url: str


class RunManager:
    """One run at a time. Keeps the current run's events so late subscribers can replay them."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.events: list[dict] = []
        self.run_id = ""
        self.task: asyncio.Task | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self.last_run_file = cfg.path(cfg.db_path).parent / "last_run.json"
        self.last_run: dict = self._load_last_run()

    def _load_last_run(self) -> dict:
        with suppress(OSError, ValueError):
            return json.loads(self.last_run_file.read_text(encoding="utf-8"))
        return {}

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def emit(self, event: dict) -> None:
        event = {"run": self.run_id, "seq": len(self.events), "t": now(), **event}
        self.events.append(event)
        for q in list(self.subscribers):
            q.put_nowait(event)

    def start(self, req: RunRequest) -> None:
        if self.running:
            raise HTTPException(409, "A run is already in progress")
        if not req.skip_exa and not os.environ.get("EXA_API_KEY"):
            raise HTTPException(400, "EXA_API_KEY is not set. Add it to job_finder/.env or turn on Skip Exa.")
        self.events = []
        self.run_id = now()
        self.task = asyncio.create_task(self._run(req))

    async def _run(self, req: RunRequest) -> None:
        started = now()
        try:
            summary = await run_pipeline(
                self.cfg, skip_exa=req.skip_exa, playwright=req.playwright,
                include_unknown=req.include_unknown, emit=self.emit,
            )
            self.last_run = {"started": started, "finished": now(), **summary}
            self.last_run_file.parent.mkdir(parents=True, exist_ok=True)
            self.last_run_file.write_text(json.dumps(self.last_run), encoding="utf-8")
        except Exception as e:  # surface every failure to the UI
            self.emit({"type": "run_error", "message": f"{type(e).__name__}: {e}"})


def create_app(config_path: str | Path = HERE / "config.yaml") -> FastAPI:
    cfg = load_config(config_path)
    manager = RunManager(cfg)
    app = FastAPI(title="Job Link Finder")
    app.state.manager = manager

    def store() -> Store:
        return Store(cfg.path(cfg.db_path))

    @app.get("/")
    def index():
        return FileResponse(UI_DIR / "index.html")

    @app.get("/api/state")
    def state():
        s = store()
        try:
            closed = s.db.execute("SELECT COUNT(*) FROM jobs WHERE status='closed'").fetchone()[0]
            companies = len(s.companies())
        finally:
            s.close()
        return {
            "running": manager.running,
            "events": manager.events,
            "last_run": manager.last_run,
            "closed": closed,
            "companies": companies,
            "exa_key_set": bool(os.environ.get("EXA_API_KEY")),
            "queries": cfg.queries,
            "roles": cfg.roles,
            "locations": cfg.locations,
        }

    @app.get("/api/jobs")
    def jobs():
        s = store()
        try:
            rows = dedupe([dict(r) for r in s.jobs(("open", "unknown"))])
        finally:
            s.close()
        since = manager.last_run.get("started", "")
        for r in rows:
            r["is_new"] = bool(since) and (r["first_seen"] or "") >= since
        return rows

    @app.get("/api/companies")
    def companies():
        s = store()
        try:
            return [dict(r) for r in s.company_rows()]
        finally:
            s.close()

    @app.post("/api/companies")
    def add_company(req: BoardRequest):
        board = ats.detect_board(req.url.strip())
        if not board:
            raise HTTPException(400, "Not a Greenhouse, Lever, Ashby, SmartRecruiters or Workday URL")
        s = store()
        try:
            s.add_company(board)
        finally:
            s.close()
        return {"ats": board.ats, "board_id": board.board_id}

    @app.delete("/api/companies/{ats_name}/{board_id}")
    def remove_company(ats_name: str, board_id: str):
        s = store()
        try:
            if not s.remove_company(Board(ats_name, board_id)):
                raise HTTPException(404, "No such board")
        finally:
            s.close()
        return {"ok": True}

    @app.post("/api/run")
    async def run(req: RunRequest):
        manager.start(req)
        return {"started": True}

    @app.get("/api/events")
    async def events(request: Request):
        # Copying the backlog and subscribing happen with no await in between, so no event is
        # lost or sent twice. Clients drop events they already applied by (run, seq).
        queue: asyncio.Queue = asyncio.Queue()
        backlog = list(manager.events)
        manager.subscribers.add(queue)

        async def stream():
            try:
                for e in backlog:
                    yield f"data: {json.dumps(e)}\n\n"
                while not await request.is_disconnected():
                    try:
                        e = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(e)}\n\n"
            finally:
                manager.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app

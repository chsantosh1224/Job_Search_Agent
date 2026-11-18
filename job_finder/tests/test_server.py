import time

import yaml
from fastapi.testclient import TestClient

from server import create_app
from settings import HERE


def _app(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    cfg |= {"db_path": str(tmp_path / "jobs.db"), "raw_dir": str(tmp_path / "raw"), "out_dir": str(tmp_path / "out")}
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return create_app(path)


def test_boards_and_state(tmp_path, monkeypatch):
    with TestClient(_app(tmp_path, monkeypatch)) as c:
        assert c.get("/").status_code == 200
        s = c.get("/api/state").json()
        assert s["running"] is False and s["exa_key_set"] is False and s["companies"] == 0
        assert c.post("/api/companies", json={"url": "https://www.linkedin.com/jobs/1"}).status_code == 400
        assert c.post("/api/companies", json={"url": "https://jobs.lever.co/acme/123"}).json() == \
            {"ats": "lever", "board_id": "acme"}
        assert [b["board_id"] for b in c.get("/api/companies").json()] == ["acme"]
        assert c.delete("/api/companies/lever/acme").status_code == 200
        assert c.delete("/api/companies/lever/acme").status_code == 404
        assert c.get("/api/jobs").json() == []


def test_run_requires_key_unless_skipping_exa(tmp_path, monkeypatch):
    with TestClient(_app(tmp_path, monkeypatch)) as c:
        r = c.post("/api/run", json={"skip_exa": False})
        assert r.status_code == 400 and "EXA_API_KEY" in r.json()["detail"]
        assert c.post("/api/run", json={"skip_exa": True, "playwright": False}).status_code == 200
        for _ in range(100):
            state = c.get("/api/state").json()
            if not state["running"]:
                break
            time.sleep(0.05)
        types = [e["type"] for e in state["events"]]
        assert types[0] == "run_start" and types[-1] == "run_done"
        assert len({e["run"] for e in state["events"]}) == 1
        assert state["last_run"]["exported"] == 0

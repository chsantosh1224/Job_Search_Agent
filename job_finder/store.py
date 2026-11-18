"""SQLite storage: jobs (keyed by stable job key) and companies (known ATS boards)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ats import Board
from models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT, location TEXT, work_mode TEXT, experience_required TEXT,
    posted_date TEXT, apply_url TEXT, source TEXT, ats TEXT, board_id TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_checked TEXT
);
CREATE INDEX IF NOT EXISTS jobs_board ON jobs(ats, board_id);
CREATE TABLE IF NOT EXISTS companies (
    ats TEXT NOT NULL, board_id TEXT NOT NULL, name TEXT,
    first_seen TEXT NOT NULL, last_fetched TEXT, last_error TEXT,
    PRIMARY KEY (ats, board_id)
);
"""
_FIELDS = ["url", "title", "company", "location", "work_mode", "experience_required",
           "posted_date", "apply_url", "source", "ats", "board_id"]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.commit()
        self.db.close()

    def upsert_job(self, job: Job, ts: str | None = None) -> None:
        """Insert, or update keeping existing values where the new ones are empty.
        Board data wins over Exa data (it comes straight from the ATS)."""
        ts = ts or now()
        row = self.db.execute("SELECT * FROM jobs WHERE key=?", (job.key,)).fetchone()
        new = job.model_dump()
        if row is None:
            self.db.execute(
                f"INSERT INTO jobs (key, {', '.join(_FIELDS)}, status, first_seen, last_seen, last_checked)"
                f" VALUES (?, {', '.join('?' * len(_FIELDS))}, ?, ?, ?, ?)",
                [job.key, *(new[f] for f in _FIELDS), job.status, ts, ts,
                 ts if job.status != "unknown" else None],
            )
            return
        board_wins = job.source == "board"
        merged = {}
        for f in _FIELDS:
            old, val = row[f], new[f]
            if f == "work_mode":
                merged[f] = val if val != "unknown" and (board_wins or old in (None, "", "unknown")) else old
            else:
                merged[f] = val if val and (board_wins or not old) else old
        if row["source"] == "board" and not board_wins:
            merged["source"] = "board"
        status = job.status if job.status != "unknown" else row["status"]
        self.db.execute(
            f"UPDATE jobs SET {', '.join(f + '=?' for f in _FIELDS)}, status=?, last_seen=?,"
            " last_checked=COALESCE(?, last_checked) WHERE key=?",
            [*(merged[f] for f in _FIELDS), status, ts,
             ts if job.status != "unknown" else None, job.key],
        )

    def set_status(self, key: str, status: str, ts: str | None = None) -> None:
        self.db.execute("UPDATE jobs SET status=?, last_checked=? WHERE key=?", (status, ts or now(), key))

    def close_missing(self, board: Board, live_keys: set[str], ts: str | None = None) -> int:
        """Board fetched completely: any open job of that board not on it any more is closed."""
        rows = self.db.execute(
            "SELECT key FROM jobs WHERE ats=? AND lower(board_id)=lower(?) AND status!='closed'",
            (board.ats, board.board_id),
        ).fetchall()
        gone = [r["key"] for r in rows if r["key"] not in live_keys]
        for key in gone:
            self.set_status(key, "closed", ts)
        return len(gone)

    def add_company(self, board: Board, name: str = "") -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO companies (ats, board_id, name, first_seen) VALUES (?, ?, ?, ?)",
            (board.ats, board.board_id, name or board.board_id, now()),
        )

    def remove_company(self, board: Board) -> bool:
        cur = self.db.execute("DELETE FROM companies WHERE ats=? AND board_id=?", (board.ats, board.board_id))
        return cur.rowcount > 0

    def company_rows(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM jobs j WHERE j.ats=c.ats AND lower(j.board_id)=lower(c.board_id)"
            " AND j.status='open') AS open_jobs FROM companies c ORDER BY open_jobs DESC, c.board_id"
        ).fetchall()

    def companies(self) -> list[Board]:
        rows = self.db.execute("SELECT ats, board_id FROM companies ORDER BY ats, board_id")
        return [Board(r["ats"], r["board_id"]) for r in rows]

    def mark_company(self, board: Board, error: str | None) -> None:
        self.db.execute(
            "UPDATE companies SET last_fetched=?, last_error=? WHERE ats=? AND board_id=?",
            (now(), error, board.ats, board.board_id),
        )

    def jobs(self, statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        if statuses:
            q = f"SELECT * FROM jobs WHERE status IN ({', '.join('?' * len(statuses))})"
            return self.db.execute(q, statuses).fetchall()
        return self.db.execute("SELECT * FROM jobs").fetchall()

    def commit(self):
        self.db.commit()

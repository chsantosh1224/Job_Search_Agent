"""Write open jobs to CSV + JSON, deduplicated."""

import csv
import json
import re
from pathlib import Path

COLUMNS = ["title", "company", "location", "work_mode", "experience_required", "posted_date",
           "url", "apply_url", "ats", "source", "status", "first_seen", "last_seen", "key"]


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def dedupe(rows: list[dict]) -> list[dict]:
    """Rows are already unique by key; also collapse the same job reached via different URLs
    (same company + title + location), preferring the board-sourced copy."""
    rows = sorted(rows, key=lambda r: (r["source"] != "board", r["first_seen"] or ""))
    seen, out = set(), []
    for r in rows:
        sig = (_norm(r["company"]), _norm(r["title"]), _norm(r["location"]))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return sorted(out, key=lambda r: (r["posted_date"] or "", r["last_seen"] or ""), reverse=True)


def write(rows: list[dict], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = out_dir / "jobs.csv", out_dir / "jobs.json"
    data = [{c: r.get(c) or "" for c in COLUMNS} for r in rows]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(data)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return csv_path, json_path


def export(store, out_dir: Path, include_unknown: bool = False) -> tuple[int, Path, Path]:
    statuses = ("open", "unknown") if include_unknown else ("open",)
    rows = dedupe([dict(r) for r in store.jobs(statuses)])
    csv_path, json_path = write(rows, out_dir)
    return len(rows), csv_path, json_path

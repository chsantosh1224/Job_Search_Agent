from ats import Board, make_key
from ats.common import iso_date, mode_from_location, work_mode
from models import Job


def parse(board: Board, payload: dict) -> list[Job]:
    jobs = []
    for j in payload.get("jobs", []):
        location = (j.get("location") or {}).get("name", "")
        meta_mode = next(
            (m.get("value") for m in j.get("metadata") or []
             if "workplace" in (m.get("name") or "").lower() or "location type" in (m.get("name") or "").lower()),
            None,
        )
        mode = work_mode(meta_mode)
        jobs.append(Job(
            key=make_key(board, str(j["id"])),
            url=j["absolute_url"],
            apply_url=j["absolute_url"],
            title=j.get("title", ""),
            company=j.get("company_name") or board.board_id,
            location=location,
            work_mode=mode if mode != "unknown" else mode_from_location(location),
            posted_date=iso_date(j.get("first_published") or j.get("updated_at")),
            source="board", ats=board.ats, board_id=board.board_id, status="open",
        ))
    return jobs


async def fetch_board(client, board: Board):
    # content=true is not needed for title/location filtering and makes payloads ~50x larger.
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{board.board_id}/jobs")
    r.raise_for_status()
    return parse(board, r.json()), True

from ats import Board, make_key
from ats.common import iso_date, mode_from_location, work_mode
from models import Job


def parse(board: Board, payload: list) -> list[Job]:
    jobs = []
    for p in payload:
        cats = p.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location") or ""]
        location = "; ".join(l for l in locations if l)
        mode = work_mode(p.get("workplaceType"))
        jobs.append(Job(
            key=make_key(board, p["id"]),
            url=p["hostedUrl"],
            apply_url=p.get("applyUrl") or p["hostedUrl"],
            title=p.get("text", ""),
            company=board.board_id,
            location=location,
            work_mode=mode if mode != "unknown" else mode_from_location(location),
            posted_date=iso_date(p.get("createdAt")),
            source="board", ats=board.ats, board_id=board.board_id, status="open",
        ))
    return jobs


async def fetch_board(client, board: Board):
    r = await client.get(f"https://api.lever.co/v0/postings/{board.board_id}", params={"mode": "json"})
    r.raise_for_status()
    return parse(board, r.json()), True

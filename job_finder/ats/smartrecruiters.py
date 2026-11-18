from ats import Board, make_key
from ats.common import iso_date, work_mode
from models import Job

PAGE = 100
MAX_PAGES = 20


def parse(board: Board, payload: dict) -> list[Job]:
    jobs = []
    for p in payload.get("content", []):
        loc = p.get("location") or {}
        location = loc.get("fullLocation") or ", ".join(
            x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x
        )
        if loc.get("remote"):
            mode = "remote"
        elif loc.get("hybrid"):
            mode = "hybrid"
        else:
            mode = work_mode(p.get("locationType")) if p.get("locationType") else "onsite"
        url = f"https://jobs.smartrecruiters.com/{board.board_id}/{p['id']}"
        jobs.append(Job(
            key=make_key(board, str(p["id"])),
            url=url, apply_url=url,
            title=p.get("name", ""),
            company=(p.get("company") or {}).get("name") or board.board_id,
            location=location,
            work_mode=mode,
            posted_date=iso_date(p.get("releasedDate")),
            source="board", ats=board.ats, board_id=board.board_id, status="open",
        ))
    return jobs


async def fetch_board(client, board: Board):
    jobs: list[Job] = []
    for page in range(MAX_PAGES):
        r = await client.get(
            f"https://api.smartrecruiters.com/v1/companies/{board.board_id}/postings",
            params={"limit": PAGE, "offset": page * PAGE},
        )
        r.raise_for_status()
        data = r.json()
        jobs += parse(board, data)
        if (page + 1) * PAGE >= data.get("totalFound", 0):
            return jobs, True
    return jobs, False

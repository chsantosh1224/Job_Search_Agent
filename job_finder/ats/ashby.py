from ats import Board, make_key
from ats.common import iso_date, mode_from_location, work_mode
from models import Job


def parse(board: Board, payload: dict) -> list[Job]:
    jobs = []
    for j in payload.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locations = [j.get("location") or ""] + [
            s.get("location", "") for s in j.get("secondaryLocations") or []
        ]
        location = "; ".join(l for l in locations if l)
        mode = work_mode(j.get("workplaceType"))
        if mode == "unknown" and j.get("isRemote"):
            mode = "remote"
        jobs.append(Job(
            key=make_key(board, j["id"]),
            url=j["jobUrl"],
            apply_url=j.get("applyUrl") or j["jobUrl"],
            title=j.get("title", ""),
            company=board.board_id,
            location=location,
            work_mode=mode if mode != "unknown" else mode_from_location(location),
            posted_date=iso_date(j.get("publishedAt")),
            source="board", ats=board.ats, board_id=board.board_id, status="open",
        ))
    return jobs


async def fetch_board(client, board: Board):
    r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board.board_id}")
    r.raise_for_status()
    return parse(board, r.json()), True

from pydantic import BaseModel


class Job(BaseModel):
    """One job posting. `key` is stable across sources (ATS job id when known, else URL)."""

    key: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    work_mode: str = "unknown"  # onsite | hybrid | remote | unknown
    experience_required: str = ""
    posted_date: str = ""  # YYYY-MM-DD when known
    apply_url: str = ""
    source: str = ""  # exa:A / exa:B / exa:C / board
    ats: str = ""
    board_id: str = ""
    status: str = "unknown"  # open | closed | unknown

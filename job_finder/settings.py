"""Load config.yaml into a typed object. Relative paths resolve against this folder."""

from pathlib import Path

import yaml
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent


class Config(BaseModel):
    roles: list[str]
    locations: list[str]
    main_query: str
    extra_queries: list[str] = []
    ats_domains: list[str] = []
    exclude_domains: list[str] = []
    target_company_domains: list[str] = []
    published_within_days: int = 14
    num_results: int = 100
    search_type: str = "deep"
    user_location: str = "IN"
    max_age_hours: int | None = 0
    livecrawl_timeout_ms: int = 10000
    highlights_max_chars: int = 1500
    role_patterns: list[str] = []
    exclude_title_patterns: list[str] = []
    onsite_location_patterns: list[str] = ["bengaluru", "bangalore"]
    remote_region_patterns: list[str] = [r"\bindia\b"]
    agency_keywords: list[str] = []
    concurrency: int = 5
    db_path: str = "data/jobs.db"
    raw_dir: str = "data/raw"
    out_dir: str = "output"

    @property
    def queries(self) -> list[str]:
        return [self.main_query, *self.extra_queries]

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else HERE / p


def load_config(path: str | Path = HERE / "config.yaml") -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))

"""Role / location / agency filters. Patterns come from config.yaml."""

import re

from models import Job
from settings import Config


class Filters:
    def __init__(self, cfg: Config):
        self.roles = [re.compile(p, re.I) for p in cfg.role_patterns]
        self.exclude_titles = [re.compile(p, re.I) for p in cfg.exclude_title_patterns]
        self.onsite = [re.compile(p, re.I) for p in cfg.onsite_location_patterns]
        self.remote_regions = [re.compile(p, re.I) for p in cfg.remote_region_patterns]
        self.agency = [k.lower() for k in cfg.agency_keywords]

    def role_ok(self, title: str) -> bool:
        return any(p.search(title) for p in self.roles) and not any(
            p.search(title) for p in self.exclude_titles
        )

    def location_ok(self, location: str, work_mode: str = "unknown") -> bool:
        """Bengaluru (any mode), or remote within India. Bare 'Remote' with no region is rejected."""
        if any(p.search(location) for p in self.onsite):
            return True
        remote = work_mode == "remote" or re.search(r"remote|work from home|\bwfh\b", location, re.I)
        return bool(remote and any(p.search(location) for p in self.remote_regions))

    def is_agency(self, company: str) -> bool:
        c = company.lower()
        return any(k in c for k in self.agency)

    def keep(self, job: Job, extra_location_text: str = "") -> bool:
        location = job.location or extra_location_text
        return (
            self.role_ok(job.title)
            and self.location_ok(location, job.work_mode)
            and not self.is_agency(job.company)
        )

import pytest

from filters import Filters
from models import Job


@pytest.mark.parametrize("title,ok", [
    ("SDET II", True), ("Software Development Engineer in Test", True),
    ("Senior QA Automation Engineer", True), ("Test Automation Engineer", True),
    ("AI Engineer", True), ("GenAI Engineer", True), ("Senior AI Automation Engineer", True),
    ("LLM Engineer", True), ("AI Quality Engineer", True),
    ("Backend Engineer", False), ("SDET Intern", False), ("Sales Executive", False),
])
def test_roles(cfg, title, ok):
    assert Filters(cfg).role_ok(title) is ok


@pytest.mark.parametrize("loc,mode,ok", [
    ("Bengaluru, Karnataka", "onsite", True), ("Bangalore / Hybrid", "hybrid", True),
    ("Remote - India", "unknown", True), ("India", "remote", True),
    ("Remote", "remote", False), ("Remote - US", "remote", False),
    ("Hyderabad, India", "onsite", False), ("", "unknown", False),
])
def test_locations(cfg, loc, mode, ok):
    assert Filters(cfg).location_ok(loc, mode) is ok


def test_keep_rejects_agency(cfg):
    f = Filters(cfg)
    job = Job(key="k", url="u", title="SDET", company="ABC Staffing Pvt Ltd", location="Bengaluru")
    assert not f.keep(job)
    assert f.keep(job.model_copy(update={"company": "Acme"}))
    assert f.keep(job.model_copy(update={"company": "Acme", "location": ""}),
                  extra_location_text="Location: Bangalore")

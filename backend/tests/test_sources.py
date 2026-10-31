import html
import json

from app.sources.ats import parse_ashby, parse_greenhouse, parse_lever
from app.sources.base import find_ats_links
from app.sources.hackernews import parse_header, parse_thread
from app.sources.remote_boards import parse_remoteok, parse_remotive
from app.sources.yc import build_job, page_props, split_location


def test_parse_hn_header():
    company, title, location = parse_header(
        "Sidekick Labs | Senior SWE, R&D Engineer | REMOTE (US Timezones) | Full-time | $170k"
    )
    assert company == "Sidekick Labs"
    assert title == "Senior SWE, R&D Engineer"
    assert location == "REMOTE (US Timezones)"


def test_parse_hn_header_with_location_in_company_part():
    company, title, location = parse_header(
        "PrairieLearn (Remote US) — Full-Stack Software Engineer — TypeScript"
    )
    assert company == "PrairieLearn"
    assert title == "Full-Stack Software Engineer"
    assert location == "PrairieLearn (Remote US)"


def test_parse_hn_prose_header_keeps_company_short():
    company, title, _ = parse_header(
        "DuckDuckGo - we are looking for candidates that are excited to join us on a mission"
    )
    assert company == "DuckDuckGo"
    assert len(title) <= 200


def test_parse_hn_header_drops_parenthesis_cut_by_separator():
    company, _, location = parse_header("Smarkets (London | Remote) | AI Engineer")
    assert company == "Smarkets"
    assert location == "Remote)"


def test_parse_hn_header_uses_first_line_only():
    company, _, _ = parse_header("LiveKit | Remote\nLiveKit is building the infrastructure")
    assert company == "LiveKit"


def test_yc_split_location_ignores_office_cities():
    assert split_location("San Francisco, CA, US / Remote (US)") == ("Remote (US)", "remote")
    assert split_location("IN / Remote (IN)") == ("Remote (IN)", "remote")
    assert split_location("San Francisco, CA, US") == ("San Francisco, CA, US", "onsite")


def test_parse_hn_thread_extracts_salary_and_ats_link():
    thread = {"id": 1, "children": [
        {"id": 42, "created_at": "2026-10-01T16:00:00Z",
         "text": "Acme | AI Engineer | REMOTE | $150k-$190k<p>Apply: "
                 "<a href=\"https:&#x2F;&#x2F;jobs.ashbyhq.com&#x2F;acme\">here</a>"},
        {"id": 43, "created_at": "2026-10-01T16:00:00Z", "text": None},
    ]}
    [job] = list(parse_thread(thread))
    assert (job.company_name, job.title, job.location) == ("Acme", "AI Engineer", "REMOTE")
    assert job.salary.currency == "USD"
    assert job.url == "https://news.ycombinator.com/item?id=42"
    assert job.ats_links == {("ashby", "acme")}


def test_find_ats_links():
    text = ("https://boards.greenhouse.io/foo/jobs/1 https://jobs.lever.co/bar/abc "
            "https://job-boards.greenhouse.io/embed/job_board?for=baz")
    assert find_ats_links(text) == {("greenhouse", "foo"), ("lever", "bar"), ("greenhouse", "baz")}


def test_yc_page_props_and_build_job():
    posting = {
        "id": 7, "title": "AI Engineer", "url": "/companies/acme/jobs/x-ai-engineer",
        "location": "IN / Remote (IN)", "salaryRange": "₹40L - ₹60L", "companyName": "Acme",
        "companyBatchName": "W24", "companyOneLiner": "Agents for invoices", "visa": None,
    }
    page = f'<div data-page="{html.escape(json.dumps({"props": {"jobPostings": [posting]}}))}">'
    assert page_props(page)["jobPostings"][0]["id"] == 7

    detail = {
        "job": {**posting, "description": "## Role\nBuild **agents**",
                "hiringManager": {"first_name": "Asha", "last_name": "Rao"}},
        "company": {"website": "https://acme.dev", "long_description": "Acme builds agents.",
                    "founders": [{"full_name": "Ravi K", "title": "CEO", "linkedin_url": "li"}]},
    }
    job = build_job(posting, detail)
    assert job.url == "https://www.ycombinator.com/companies/acme/jobs/x-ai-engineer"
    assert job.salary.max_inr == 6_000_000
    assert job.company_website == "https://acme.dev"
    assert job.extra["hiring_manager"] == "Asha Rao"
    assert job.extra["founders"] == [{"name": "Ravi K", "title": "CEO", "linkedin": "li"}]
    assert "Build **agents**" in job.description

    # Without a detail page (already-known job) the listing data still builds a job.
    assert build_job(posting, None).extra["hiring_manager"] is None


def test_parse_remoteok_skips_legal_notice_and_converts_salary():
    items = [{"legal": "..."}, {
        "id": "9", "position": "LLM Engineer", "company": "Foo", "location": "",
        "salary_min": 100000, "salary_max": 0, "date": "2026-10-25T12:00:00+00:00",
        "url": "https://remoteok.com/x", "description": "<p>Hi</p>",
    }]
    [job] = list(parse_remoteok(items))
    assert job.workplace == "remote"
    assert job.location is None
    assert job.salary.min_inr == job.salary.max_inr == 100_000 * 88


def test_parse_remotive_uses_usd_for_bare_salary():
    [job] = list(parse_remotive({"jobs": [{
        "id": 1, "url": "u", "title": "QA Automation Engineer", "company_name": "Bar",
        "candidate_required_location": "Worldwide", "salary": "70K-80K",
        "publication_date": "2026-10-22T18:40:19", "description": "<p>x</p>",
    }]}))
    assert job.salary.currency == "USD"
    assert job.posted_at.tzinfo is not None


def test_parse_greenhouse_reads_location_type():
    [job] = list(parse_greenhouse("acme", "Acme", {"jobs": [{
        "id": 5, "title": "AI Engineer", "absolute_url": "u", "location": {"name": "Remote"},
        "metadata": [{"name": "Location Type", "value": "Remote"}],
        "content": "&lt;p&gt;Pay: $150,000 - $200,000&lt;/p&gt;",
        "first_published": "2026-10-19T11:17:24-04:00",
    }]}))
    assert job.source_job_id == "acme:5"
    assert (job.location, job.workplace) == ("Remote", "remote")
    assert job.salary.currency == "USD"


def test_parse_lever_structured_salary_and_remote():
    [job] = list(parse_lever("acme", "Acme", [{
        "id": "abc", "text": "Automation Engineer", "hostedUrl": "u",
        "categories": {"location": "India", "commitment": "Full-time"},
        "workplaceType": "remote", "descriptionPlain": "Build things",
        "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
        "salaryRange": {"min": 4000000, "max": 6000000, "currency": "INR",
                        "interval": "per-year-salary"},
        "createdAt": 1792931661000,
    }]))
    assert (job.location, job.workplace) == ("India", "remote")
    assert job.salary.max_inr == 6_000_000
    assert job.salary.raw == "4000000-6000000 INR per year"
    assert "Requirements\nPython" in job.description


def test_parse_ashby_skips_unlisted():
    jobs = list(parse_ashby("acme", "Acme", {"jobs": [
        {"id": "1", "title": "AI Engineer", "isListed": True, "location": "Remote",
         "isRemote": True, "jobUrl": "u", "descriptionPlain": "d",
         "compensation": {"scrapeableCompensationSalarySummary": "$150K - $200K"},
         "publishedAt": "2026-10-01T00:00:00.000+00:00"},
        {"id": "2", "title": "Hidden", "isListed": False, "jobUrl": "u"},
    ]}))
    assert [j.source_job_id for j in jobs] == ["acme:1"]
    assert jobs[0].salary.max_inr == 200_000 * 88

from datetime import date

from exa_search import build_payload, parse_response, parse_summary


def test_empty_domain_lists_skip_runs(cfg):
    cfg = cfg.model_copy(update={"ats_domains": [], "target_company_domains": []})
    today = date(2026, 11, 18)
    assert build_payload(cfg, "q", "A", today) is None
    assert build_payload(cfg, "q", "C", today) is None
    assert build_payload(cfg, "q", "B", today) is not None


def test_payload_runs(cfg):
    cfg = cfg.model_copy(update={"ats_domains": ["jobs.lever.co"]})
    today = date(2026, 11, 18)
    a = build_payload(cfg, "q", "A", today)
    b = build_payload(cfg, "q", "B", today)
    assert a["includeDomains"] == cfg.ats_domains and "excludeDomains" not in a
    assert b["excludeDomains"] == cfg.exclude_domains and "includeDomains" not in b
    assert build_payload(cfg, "q", "C", today) is None  # no target domains yet
    assert a["startPublishedDate"] == "2026-11-04T00:00:00.000Z"
    assert a["type"] == "deep" and a["numResults"] == 100 and a["userLocation"] == "IN"
    c = a["contents"]
    assert c["highlights"]["maxCharacters"] == 1500 and c["maxAgeHours"] == 0
    assert len(c["summary"]["schema"]["properties"]) == 10


def test_parse_summary_variants():
    assert parse_summary('{"is_job_posting": true, "is_open": true, "job_title": "SDET"}').job_title == "SDET"
    assert parse_summary('```json\n{"is_job_posting": true}\n```').is_job_posting
    assert parse_summary({"is_job_posting": True, "work_mode": "Remote-ish"}).work_mode == "unknown"
    assert parse_summary("not json") is None


def test_candidates():
    resp = {"results": [
        {"url": "https://jobs.lever.co/a/1", "title": "t", "publishedDate": "2026-11-10T00:00:00.000Z",
         "summary": '{"is_job_posting": true, "is_open": true, "job_title": "SDET", "company": "A", '
                    '"posted_by_agency": false}'},
        {"url": "https://x.com/2", "summary": '{"is_job_posting": true, "is_open": false}'},
        {"url": "https://x.com/3", "summary": '{"is_job_posting": true, "is_open": true, "posted_by_agency": true}'},
        {"url": "https://x.com/4"},
    ]}
    hits = parse_response(resp, "A", "q")
    assert [h.is_candidate for h in hits] == [True, False, False, False]
    assert hits[0].published_date == "2026-11-10"

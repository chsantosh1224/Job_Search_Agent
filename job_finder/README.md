# Job Link Finder

Finds live job postings that companies publish on their own ATS boards or career sites.
Aggregators, agencies and expired posts are excluded. Roles: SDET, QA Automation Engineer,
AI Automation Engineer and AI Engineer. Locations: Bengaluru or remote India.
Output is `output/jobs.csv` and `output/jobs.json`. Scoring and applying happen in a separate pipeline.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then set EXA_API_KEY
# optional, for JS-rendered pages during liveness checks:
pip install playwright && python -m playwright install chromium
```

## Use

```bash
python main.py run                 # Exa discovery -> board expansion -> liveness -> export
python main.py run --skip-exa      # re-check known boards + stored jobs only (no Exa cost)
python main.py export              # re-export from data/jobs.db
python main.py add-board <url>     # seed a company board by any of its URLs
python main.py ui                  # web UI at http://127.0.0.1:8765
python -m pytest                   # tests (no network)
```

## Web UI

`python main.py ui` serves a single page, `ui/index.html`, from FastAPI (`server.py`).
It needs no build step. You can start a run (with or without Exa), watch each pipeline stage
live (progress streams from the server), browse and filter the open roles, and add or remove
tracked company boards. Only one run happens at a time. If you reload the page mid-run, it
picks up where it was.

## How it works

1. **Discovery** (`exa_search.py`): each query runs as Run A (ATS domains only), Run B
   (everything except aggregators) and Run C (target company domains; skipped while
   `target_company_domains` is empty). Each result gets structured fields through
   `contents.summary.schema`. Results are kept only when `is_job_posting && is_open &&
   !posted_by_agency` and they pass the role and location filters. Raw responses are saved
   in `data/raw/<date>/`.
2. **Board expansion** (`ats/`): every Greenhouse, Lever, Ashby, SmartRecruiters or Workday URL
   that Exa returns registers that company's board in SQLite. Each run re-fetches all known boards
   for free and keeps only matching jobs. A job that disappears from a fully fetched board is
   marked closed.
3. **Liveness** (`liveness.py`): a job that a board API confirmed in this run counts as live.
   Every other job is fetched with up to 5 concurrent requests. A job is marked closed on a
   404 or 410, a redirect that drops the posting id, Greenhouse `?error=true`, or closed-job
   wording. A 403, 429 or 5xx response, or a JS page with no content, sets the status to
   `unknown` (Playwright is tried first when it's installed). Unknown jobs are left out of
   the export unless you pass `--include-unknown`.
4. **Export** (`export.py`): writes only open jobs. Duplicates are removed by stable job key
   (`ats:board:job_id`) and then by company + title + location.

Jobs are keyed by ATS job id rather than URL. So `boards.greenhouse.io/x/jobs/1`,
`job-boards.greenhouse.io/x/jobs/1?utm=…` and the board API's own copy of that job all
resolve to the same row.

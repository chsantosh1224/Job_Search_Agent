import argparse
import logging
import sys
from pathlib import Path


def _user(session, email: str | None):
    """The user for --email, or the first admin when no email is given."""
    from sqlalchemy import select

    from app.models import User
    from app.users import primary_admin

    user = (session.scalar(select(User).where(User.email == email.strip().lower()))
            if email else primary_admin(session))
    if user is None:
        sys.exit(f"No user {'with email ' + email if email else '(no admin yet)'}. "
                 "Sign in once, or run: jobagent bootstrap-admin")
    return user


def cmd_bootstrap_admin(args: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.db import session_scope
    from app.users import bootstrap_admin

    email = args.email or next(iter(sorted(get_settings().admin_email_set)), None)
    if not email:
        sys.exit("Give --email or set ADMIN_EMAILS")
    with session_scope() as session:
        user, claimed = bootstrap_admin(session, email)
        print(f"Admin account #{user.id} ({user.email}); took over existing data: {claimed}")
        print("It is linked to Google on the first sign-in with this email.")


def cmd_ingest_resume(args: argparse.Namespace) -> None:
    from app.db import session_scope
    from app.embeddings import get_embedder
    from app.resume.ingest import ingest_resume

    with session_scope() as session:
        user = _user(session, args.email)
        resume = ingest_resume(session, Path(args.path), get_embedder(), user_id=user.id)
        print(f"Active resume for {user.email}: #{resume.id} {resume.filename} "
              f"({len(resume.chunks)} chunks)")


def cmd_show_resume(args: argparse.Namespace) -> None:
    from app.db import session_scope
    from app.resume.ingest import get_active_resume

    with session_scope() as session:
        user = _user(session, args.email)
        resume = get_active_resume(session, user.id)
        if resume is None:
            print("No active resume. Run: jobagent ingest-resume <path-to-pdf>")
            return
        print(f"#{resume.id} {resume.filename}")
        for chunk in resume.chunks:
            label = f"{chunk.section}/{chunk.title}" if chunk.title else chunk.section
            print(f"  [{label}] {chunk.content[:110]}")


def cmd_fetch(args: argparse.Namespace) -> None:
    from app.fetch import run_fetch

    run = run_fetch(only=set(args.source) if args.source else None)
    print(f"Run #{run.id}: {run.status}")
    for source, stats in run.stats.items():
        print(f"  {source:<11} {stats}")


def cmd_refilter(args: argparse.Namespace) -> None:
    from app.db import session_scope
    from app.jobs_store import refilter_all

    with session_scope() as session:
        print(refilter_all(session))


def cmd_jobs(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from app.config import get_settings
    from app.db import session_scope
    from app.models import Job

    rate = get_settings().usd_to_inr
    with session_scope() as session:
        query = select(Job).order_by(Job.posted_at.desc().nulls_last()).limit(args.limit)
        if not args.all:
            query = query.where(Job.passed_filters.is_(True))
        for job in session.scalars(query):
            salary = (f"${(job.salary_min_inr or job.salary_max_inr) / rate / 1000:.0f}k-"
                      f"${job.salary_max_inr / rate / 1000:.0f}k"
                      if job.salary_max_inr else "salary unknown")
            status = "" if job.passed_filters else f"  [filtered: {job.filter_reason}]"
            company = job.company.name if job.company else "?"
            print(f"#{job.id:<5} {job.source:<10} {company[:22]:<22} {job.title[:50]:<50} "
                  f"{job.remote_type.value:<18} {salary}{status}")


def cmd_rank(args: argparse.Namespace) -> None:
    from app.db import session_scope
    from app.llm.client import LLMError
    from app.ranking.run import run_rank

    user_ids = None
    if args.email:
        with session_scope() as session:
            user_ids = [_user(session, args.email).id]
    try:
        run = run_rank(user_ids=user_ids, limit=args.limit, briefs=args.briefs)
    except LLMError as exc:
        print(f"Ranking failed: {exc}")
        return
    print(f"Run #{run.id}: {run.status}")
    print(f"  {run.stats['rank']}")
    for error in run.stats["errors"]:
        print(f"  ! {error}")


def cmd_matches(args: argparse.Namespace) -> None:
    from sqlalchemy import and_, select

    from app.db import session_scope
    from app.models import Job, JobMatch, ResearchBrief
    from app.resume.ingest import get_active_resume

    with session_scope() as session:
        resume = get_active_resume(session, _user(session, args.email).id)
        if resume is None:
            print("No active resume.")
            return
        rows = session.execute(
            select(JobMatch, Job, ResearchBrief.id)
            .join(Job, Job.id == JobMatch.job_id)
            .outerjoin(ResearchBrief, and_(ResearchBrief.job_id == Job.id,
                                           ResearchBrief.resume_id == resume.id))
            .where(JobMatch.resume_id == resume.id, JobMatch.tier.is_not(None),
                   Job.passed_filters.is_(True))
            .order_by(JobMatch.tier, JobMatch.fit_score.desc())
        )
        for match, job, brief_id in rows:
            company = job.company.name if job.company else "?"
            brief = "brief" if brief_id else ""
            print(f"T{match.tier} {match.fit_score:>3}  #{job.id:<5} {company[:20]:<20} "
                  f"{job.title[:48]:<48} {brief}")
            for reason in match.reasons[:2]:
                print(f"           + {reason[:100]}")
            for gap in match.gaps[:1]:
                print(f"           - {gap[:100]}")


def cmd_brief(args: argparse.Namespace) -> None:
    import json

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Job, ResearchBrief
    from app.resume.ingest import get_active_resume

    with session_scope() as session:
        resume = get_active_resume(session, _user(session, args.email).id)
        job = session.get(Job, args.job_id)
        brief = session.scalar(select(ResearchBrief).where(
            ResearchBrief.job_id == args.job_id,
            ResearchBrief.resume_id == (resume.id if resume else -1)))
        if job is None or brief is None:
            print("No brief for that job id. Run: jobagent matches")
            return
        print(f"{job.title} — {job.company.name if job.company else '?'}\n{job.url}\n")
        print(json.dumps(brief.content, indent=2, ensure_ascii=False))


def cmd_pipeline(args: argparse.Namespace) -> None:
    from app.pipeline import execute_run, queue_run

    run = queue_run("manual")
    if run is None:
        print("A run is already queued or in progress.")
        return
    run = execute_run(run.id)
    print(f"Run #{run.id}: {run.status}")
    for key, value in run.stats.items():
        print(f"  {key}: {value}")


def cmd_worker(args: argparse.Namespace) -> None:
    from app.pipeline import run_worker

    run_worker()


def cmd_digest(args: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.db import session_scope
    from app.digest import collect, render_html, send_digest, subject

    with session_scope() as session:
        user = _user(session, args.email)
        if args.preview:
            settings = get_settings()
            items, total = collect(session, user, settings.digest_max_jobs)
            if not items:
                print("No new matches; nothing would be sent.")
                return
            Path(args.preview).write_text(
                render_html(items, total, settings.public_url.rstrip("/")), encoding="utf-8")
            print(f"Subject: {subject(items, total)}\nPreview written to {args.preview}")
            return
        print(send_digest(session, user))


def cmd_eval(args: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.evals.run import judge_llm, rank_labeled_jobs, run_brief_eval, run_ranking_eval
    from app.llm.client import LLMError
    from app.ranking.run import default_llm

    try:
        if args.rank_labeled:
            result = rank_labeled_jobs(default_llm(get_settings()), args.rank_labeled)
            print(f"Ranked {result['ranked']} labeled job(s) the pipeline had skipped")
            for error in result["errors"]:
                print(f"  ! {error}")
        ranking = run_ranking_eval()
        m = ranking.metrics
        print(f"Ranking eval #{ranking.id}: {m['labeled']} labeled, {m['evaluated']} evaluated")
        for key in ("precision", "recall", "f1", "precision_at_5", "tier_accuracy", "auc_llm",
                    "auc_similarity"):
            print(f"  {key:<15} {m[key]}")
        if args.briefs:
            briefs = run_brief_eval(judge_llm(), args.briefs)
            if briefs:
                print(f"Brief eval #{briefs.id}: {briefs.metrics}")
    except LLMError as exc:
        print(f"Evaluation failed: {exc}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("app.api.main:app", host=args.host, port=args.port, reload=args.reload)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="jobagent")
    sub = parser.add_subparsers(required=True)

    def command(name: str, func, help: str, user: bool = False):
        p = sub.add_parser(name, help=help)
        if user:
            p.add_argument("--email", help="whose data (default: the first admin)")
        p.set_defaults(func=func)
        return p

    command("bootstrap-admin", cmd_bootstrap_admin,
            "Create the admin account and give it the existing single-user data",
            ).add_argument("--email", help="default: first of ADMIN_EMAILS")

    fetch = command("fetch", cmd_fetch, "Fetch jobs from all (or chosen) sources")
    fetch.add_argument("--source", action="append",
                       choices=["yc", "hackernews", "remotive", "remoteok", "ats"])

    command("refilter", cmd_refilter, "Re-apply the shared filters to all stored jobs")

    jobs = command("jobs", cmd_jobs, "List stored jobs (passing filters by default)")
    jobs.add_argument("--all", action="store_true", help="include filtered-out jobs")
    jobs.add_argument("--limit", type=int, default=50)

    rank = command("rank", cmd_rank, "Rank new jobs for every user (or --email) within limits")
    rank.add_argument("--email", help="only this user")
    rank.add_argument("--limit", type=int, help="rank at most N jobs per user")
    rank.add_argument("--briefs", type=int, help="write at most N briefs per user")

    command("matches", cmd_matches, "List a user's ranked jobs by tier and score", user=True)
    command("brief", cmd_brief, "Show a user's research brief for a job",
            user=True).add_argument("job_id", type=int)
    command("pipeline", cmd_pipeline, "Run fetch, rank and digests now")
    command("worker", cmd_worker, "Run the daily schedule and queued runs")
    command("digest", cmd_digest, "Send a user's email digest", user=True).add_argument(
        "--preview", metavar="FILE", help="write the email HTML to FILE instead of sending")

    evaluate = command("eval", cmd_eval, "Score ranking against labels; optionally judge briefs")
    evaluate.add_argument("--rank-labeled", type=int, default=0, metavar="N",
                          help="first LLM-rank up to N labeled jobs the pipeline skipped")
    evaluate.add_argument("--briefs", type=int, default=0, metavar="N",
                          help="LLM-judge the N most recent briefs (faithfulness)")

    serve = command("serve", cmd_serve, "Run the API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    command("ingest-resume", cmd_ingest_resume, "Parse and embed a resume PDF for a user",
            user=True).add_argument("path")
    command("show-resume", cmd_show_resume, "Print a user's active resume chunks", user=True)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

"""Ranking quality against the candidate's hand labels.

A job counts as predicted "good" when the LLM gave it a tier and a fit score at or above the
brief threshold. The embedding similarity alone is scored too (AUC), as a baseline: it shows
how much the LLM step adds over plain vector search.
"""

from dataclasses import asdict, dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import EvalLabel, Job, JobMatch
from app.resume.ingest import get_active_resume
from app.users import primary_admin


@dataclass
class LabeledJob:
    job_id: int
    title: str
    company: str | None
    good: bool  # the human label
    expected_tier: int | None
    tier: int | None
    fit_score: int | None
    similarity: float | None
    ranked: bool  # has an LLM ranking (not just an embedding similarity)


def load_labeled(session: Session) -> list[LabeledJob]:
    """The admin's labels, scored against rankings for the admin's resume."""
    admin = primary_admin(session)
    resume = get_active_resume(session, admin.id) if admin else None
    rows = session.execute(
        select(EvalLabel, Job, JobMatch)
        .join(Job, Job.id == EvalLabel.job_id)
        .outerjoin(JobMatch, and_(JobMatch.job_id == Job.id,
                                  JobMatch.resume_id == (resume.id if resume else -1)))
        .order_by(EvalLabel.id)
    ).all()
    return [
        LabeledJob(
            job_id=job.id, title=job.title, company=job.company.name if job.company else None,
            good=label.is_good_fit, expected_tier=label.expected_tier,
            tier=match.tier if match else None,
            fit_score=match.fit_score if match else None,
            similarity=match.similarity if match else None,
            ranked=bool(match and match.model),
        )
        for label, job, match in rows
    ]


def predicted_good(item: LabeledJob, threshold: int) -> bool:
    return item.tier is not None and (item.fit_score or 0) >= threshold


def auc(positives: list[float], negatives: list[float]) -> float | None:
    """Probability a random good job scores above a random bad one (ties count half)."""
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 3)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def precision_at(items: list[LabeledJob], k: int) -> float | None:
    top = sorted(items, key=lambda i: i.fit_score or 0, reverse=True)[:k]
    return _ratio(sum(i.good for i in top), len(top))


def compute_metrics(items: list[LabeledJob], threshold: int) -> dict:
    ranked = [i for i in items if i.ranked]
    tp = sum(i.good and predicted_good(i, threshold) for i in ranked)
    fp = sum(not i.good and predicted_good(i, threshold) for i in ranked)
    fn = sum(i.good and not predicted_good(i, threshold) for i in ranked)
    tn = len(ranked) - tp - fp - fn
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = (round(2 * precision * recall / (precision + recall), 3)
          if precision and recall else None)

    tiered = [i for i in ranked if i.good and i.expected_tier and i.tier]
    with_similarity = [i for i in items if i.similarity is not None]

    mistakes = [
        {**asdict(i), "kind": "false positive" if predicted_good(i, threshold) else
         "false negative"}
        for i in ranked if i.good != predicted_good(i, threshold)
    ]
    return {
        "labeled": len(items),
        "labeled_good": sum(i.good for i in items),
        "evaluated": len(ranked),
        "not_ranked_yet": len(items) - len(ranked),
        "threshold": threshold,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": _ratio(tp + tn, len(ranked)),
        "precision_at_5": precision_at(ranked, 5),
        "precision_at_10": precision_at(ranked, 10),
        "tier_accuracy": _ratio(sum(i.tier == i.expected_tier for i in tiered), len(tiered)),
        "tier_within_one": _ratio(sum(abs(i.tier - i.expected_tier) <= 1 for i in tiered),
                                  len(tiered)),
        "auc_llm": auc([i.fit_score or 0 for i in ranked if i.good],
                       [i.fit_score or 0 for i in ranked if not i.good]),
        "auc_similarity": auc([i.similarity for i in with_similarity if i.good],
                              [i.similarity for i in with_similarity if not i.good]),
        "mistakes": mistakes,
    }

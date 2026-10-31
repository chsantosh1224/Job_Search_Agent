"""Database schema.

Jobs and companies are shared by everyone. Resumes (and through them rankings and briefs),
applications and AI usage belong to a user. Eval labels are the admin's.
"""

import enum
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Timestamped, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Google's stable account id; NULL until the user first signs in (e.g. a bootstrapped admin).
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    min_salary_usd: Mapped[int | None] = mapped_column(Integer)
    # Optional note for the AI ("pivoting from RPA to AI engineering, open to mid-level").
    about: Mapped[str] = mapped_column(Text, default="", server_default="")
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Resume(Timestamped, Base):
    __tablename__ = "resumes"
    __table_args__ = (UniqueConstraint("user_id", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_text: Mapped[str] = mapped_column(Text)
    sections: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    chunks: Mapped[list["ResumeChunk"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", order_by="ResumeChunk.position"
    )
    user: Mapped[User | None] = relationship(back_populates="resumes")


class ResumeChunk(Base):
    """One section or project of the resume, embedded separately so a job can be matched to the
    specific project worth leading with (used by research briefs)."""

    __tablename__ = "resume_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    resume: Mapped[Resume] = relationship(back_populates="chunks")


class Company(Timestamped, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    funding_stage: Mapped[str | None] = mapped_column(String(100))
    yc_batch: Mapped[str | None] = mapped_column(String(20))
    ats_type: Mapped[str | None] = mapped_column(String(20))  # greenhouse | lever | ashby
    ats_slug: Mapped[str | None] = mapped_column(String(255))

    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class RemoteType(enum.StrEnum):
    REMOTE_GLOBAL = "remote_global"
    REMOTE_INDIA = "remote_india"
    REMOTE_RESTRICTED = "remote_restricted"  # remote but limited to other regions
    REMOTE_UNSPECIFIED = "remote_unspecified"  # remote, region not stated
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class Job(Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id"),
        # Cosine-similarity index for matching jobs against the resume.
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_job_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    location: Mapped[str | None] = mapped_column(String(500))
    remote_type: Mapped[RemoteType] = mapped_column(
        Enum(RemoteType, values_callable=lambda e: [m.value for m in e], name="remote_type"),
        default=RemoteType.UNKNOWN,
    )
    india_eligible: Mapped[bool | None] = mapped_column(Boolean)
    salary_raw: Mapped[str | None] = mapped_column(String(255))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    # Annual INR after currency conversion; NULL means salary unknown (shown, not hidden).
    salary_min_inr: Mapped[int | None] = mapped_column(BigInteger)
    salary_max_inr: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text, default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Hash of normalized company + title, for cross-source deduplication.
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    passed_filters: Mapped[bool | None] = mapped_column(Boolean)
    filter_reason: Mapped[str | None] = mapped_column(String(255))
    # Source-specific details for research briefs: hiring manager, founders, visa, equity, tags.
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    company: Mapped[Company | None] = relationship(back_populates="jobs")


class JobMatch(Timestamped, Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("job_id", "resume_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    similarity: Mapped[float] = mapped_column(Float)
    tier: Mapped[int | None] = mapped_column(Integer)  # 1-3, NULL = not a fit
    fit_score: Mapped[int | None] = mapped_column(Integer)  # 0-100
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    gaps: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(255))
    # When this match went out in an email digest; NULL = not emailed yet.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchBrief(Timestamped, Base):
    """Written for one resume: the lead project and talking points depend on whose it is."""

    __tablename__ = "research_briefs"
    __table_args__ = (UniqueConstraint("job_id", "resume_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[dict] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(255))


class ApplicationStatus(enum.StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class Application(Timestamped, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(
            ApplicationStatus,
            values_callable=lambda e: [m.value for m in e],
            name="application_status",
        ),
        default=ApplicationStatus.NEW,
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20))  # scheduled | manual | resume
    # Set for a ranking-only run for one user (e.g. right after they upload a resume).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class LLMUsage(Base):
    """LLM calls per user per day, for the per-user and overall daily limits."""

    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("day", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    ranked: Mapped[int] = mapped_column(Integer, default=0)
    briefs: Mapped[int] = mapped_column(Integer, default=0)


class EvalRun(Timestamped, Base):
    """One evaluation: ranking metrics against labels, or LLM-judged brief quality."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # ranking | briefs
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    details: Mapped[list] = mapped_column(JSONB, default=list)


class EvalLabel(Timestamped, Base):
    """The candidate's hand labels; ranking quality is scored against these."""

    __tablename__ = "eval_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    is_good_fit: Mapped[bool] = mapped_column(Boolean)
    expected_tier: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")

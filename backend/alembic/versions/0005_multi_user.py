"""multi-user: users, per-user resumes/briefs/applications, LLM usage

Existing single-user rows keep a NULL owner here; `jobagent bootstrap-admin` assigns them to the
admin account (see docs/MULTI_USER.md).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("min_salary_usd", sa.Integer(), nullable=True),
        sa.Column("about", sa.Text(), server_default="", nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("google_sub"),
    )

    # Resumes: owned by a user; the same file may be uploaded by different users.
    op.add_column("resumes", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "resumes", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index(op.f("ix_resumes_user_id"), "resumes", ["user_id"])
    op.drop_constraint("resumes_content_hash_key", "resumes", type_="unique")
    op.create_unique_constraint(None, "resumes", ["user_id", "content_hash"])

    # Briefs: one per job per resume. Existing briefs were written for the active resume.
    op.add_column("research_briefs", sa.Column("resume_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "research_briefs", "resumes", ["resume_id"], ["id"],
                          ondelete="CASCADE")
    op.execute("UPDATE research_briefs SET resume_id = "
               "(SELECT id FROM resumes ORDER BY is_active DESC, id DESC LIMIT 1)")
    op.drop_constraint("research_briefs_job_id_key", "research_briefs", type_="unique")
    op.create_unique_constraint(None, "research_briefs", ["job_id", "resume_id"])
    op.create_index(op.f("ix_research_briefs_job_id"), "research_briefs", ["job_id"])
    op.create_index(op.f("ix_research_briefs_resume_id"), "research_briefs", ["resume_id"])

    # Applications: one per job per user.
    op.add_column("applications", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "applications", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index(op.f("ix_applications_user_id"), "applications", ["user_id"])
    op.drop_constraint("applications_job_id_key", "applications", type_="unique")
    op.create_unique_constraint(None, "applications", ["user_id", "job_id"])

    op.add_column("pipeline_runs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "pipeline_runs", "users", ["user_id"], ["id"], ondelete="CASCADE")

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("ranked", sa.Integer(), nullable=False),
        sa.Column("briefs", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("llm_usage")
    op.drop_constraint("pipeline_runs_user_id_fkey", "pipeline_runs", type_="foreignkey")
    op.drop_column("pipeline_runs", "user_id")

    op.drop_constraint("applications_user_id_job_id_key", "applications", type_="unique")
    op.execute("DELETE FROM applications a USING applications b "
               "WHERE a.job_id = b.job_id AND a.id > b.id")
    op.create_unique_constraint("applications_job_id_key", "applications", ["job_id"])
    op.drop_index(op.f("ix_applications_user_id"), table_name="applications")
    op.drop_column("applications", "user_id")

    op.drop_constraint("research_briefs_job_id_resume_id_key", "research_briefs", type_="unique")
    op.execute("DELETE FROM research_briefs a USING research_briefs b "
               "WHERE a.job_id = b.job_id AND a.id > b.id")
    op.create_unique_constraint("research_briefs_job_id_key", "research_briefs", ["job_id"])
    op.drop_index(op.f("ix_research_briefs_resume_id"), table_name="research_briefs")
    op.drop_index(op.f("ix_research_briefs_job_id"), table_name="research_briefs")
    op.drop_column("research_briefs", "resume_id")

    op.drop_constraint("resumes_user_id_content_hash_key", "resumes", type_="unique")
    op.execute("DELETE FROM resumes a USING resumes b "
               "WHERE a.content_hash = b.content_hash AND a.id > b.id")
    op.create_unique_constraint("resumes_content_hash_key", "resumes", ["content_hash"])
    op.drop_index(op.f("ix_resumes_user_id"), table_name="resumes")
    op.drop_column("resumes", "user_id")

    op.drop_table("users")

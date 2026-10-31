from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # 127.0.0.1 rather than localhost: on Windows, localhost tries IPv6 first and stalls.
    database_url: str = "postgresql+psycopg://jobagent:jobagent@127.0.0.1:5434/jobagent"

    # Local ONNX embedding model; dimension must match the vector columns in the schema.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    openrouter_api_key: str = ""
    # Free models tried in order; the next one is used when a model errors or returns bad JSON.
    openrouter_models: str = (
        "nvidia/nemotron-3.5-super-vl:free,"
        "google/gemma-4-31b-it:free,"
        "xingchen-agi/xing4.0-29b-a4b:free,"
        "dots-studio/dots-3-note-preview:free,"
        "nvidia/nemotron-3-super-120b-a12b:free"
    )
    # Brief judge: a different model first, so briefs are not graded by the model that wrote them.
    openrouter_judge_models: str = (
        "google/gemma-4-31b-it:free,"
        "xingchen-agi/xing4.0-29b-a4b:free,"
        "nvidia/nemotron-3.5-super-vl:free"
    )
    # Free models allow ~20 requests/minute and ~1,000/day (with $10 credit).
    llm_min_interval_seconds: float = 3.5
    llm_max_calls_per_run: int = 80  # safety net for one run of one user (incl. fallbacks)

    # AI limits per user per day, and LLM calls per day across all users.
    user_daily_rank_limit: int = 20
    user_daily_brief_limit: int = 3
    llm_daily_cap: int = 800

    # Ranking: only jobs similar enough to the resume go to the LLM; briefs need this fit score.
    min_similarity: float = 0.55
    brief_min_score: int = 50

    resend_api_key: str = ""
    # Daily digest to each user's email. The "from" domain must be verified in Resend.
    digest_from: str = "Job Search Agent <digest@jobs.aicruit.in>"
    digest_max_jobs: int = 10

    # Public address of the app: links in emails and the Google sign-in redirect.
    public_url: str = "http://127.0.0.1:8000"

    # Daily run time, India time (24h "HH:MM").
    daily_run_time_ist: str = "05:00"

    # Google sign-in (OAuth client from Google Cloud console).
    google_client_id: str = ""
    google_client_secret: str = ""
    # Comma-separated emails that get admin rights (runs, evals, users).
    admin_emails: str = ""
    # Local testing only: sign in by email without Google, from localhost. Never in production.
    dev_login: bool = False

    jwt_secret: str = ""
    session_days: int = 30
    cookie_secure: bool = False  # True in production (HTTPS)

    usd_to_inr: float = 88.0
    eur_to_inr: float = 95.0
    gbp_to_inr: float = 112.0

    # Jobs posted longer ago than this are filtered out as stale.
    max_job_age_days: int = 60

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

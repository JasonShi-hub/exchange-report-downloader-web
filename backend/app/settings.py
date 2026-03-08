from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    access_password: str
    token_secret: str
    allowed_origin: str
    jobs_root: Path
    token_ttl_seconds: int
    job_retention_seconds: int
    max_stocks_per_job: int
    max_date_range_days: int
    max_queued_jobs: int
    login_rate_limit_per_minute: int
    job_rate_limit_per_minute: int


def load_settings() -> Settings:
    jobs_root = Path(os.getenv("JOBS_ROOT", "/tmp/exchange-downloader/jobs"))
    return Settings(
        access_password=os.getenv("ACCESS_PASSWORD", "").strip(),
        token_secret=os.getenv("TOKEN_SECRET", "replace-this-before-deploy").strip(),
        allowed_origin=os.getenv("ALLOWED_ORIGIN", "https://download.shijason.com").strip(),
        jobs_root=jobs_root,
        token_ttl_seconds=int(os.getenv("TOKEN_TTL_SECONDS", str(7 * 24 * 3600))),
        job_retention_seconds=int(os.getenv("JOB_RETENTION_SECONDS", "3600")),
        max_stocks_per_job=int(os.getenv("MAX_STOCKS_PER_JOB", "5")),
        max_date_range_days=int(os.getenv("MAX_DATE_RANGE_DAYS", "365")),
        max_queued_jobs=int(os.getenv("MAX_QUEUED_JOBS", "5")),
        login_rate_limit_per_minute=int(os.getenv("LOGIN_RATE_LIMIT_PER_MINUTE", "12")),
        job_rate_limit_per_minute=int(os.getenv("JOB_RATE_LIMIT_PER_MINUTE", "8")),
    )


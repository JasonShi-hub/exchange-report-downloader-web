import tempfile
import unittest
from pathlib import Path

from app.job_manager import JobManager, JobQueueFullError
from app.settings import Settings


class JobManagerTests(unittest.TestCase):
    def make_settings(self, jobs_root: Path) -> Settings:
        return Settings(
            access_password="pw",
            token_secret="secret",
            allowed_origin="https://download.shijason.com",
            jobs_root=jobs_root,
            token_ttl_seconds=3600,
            job_retention_seconds=60,
            max_stocks_per_job=5,
            max_date_range_days=365,
            max_queued_jobs=1,
            login_rate_limit_per_minute=12,
            job_rate_limit_per_minute=8,
        )

    def test_queue_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(self.make_settings(Path(tmp)))
            manager.create_job("ashare", ["000001"], "2025-01-01", "2025-01-02", [], [], "zip")
            with self.assertRaises(JobQueueFullError):
                manager.create_job("ashare", ["000002"], "2025-01-01", "2025-01-02", [], [], "zip")

    def test_cancel_queued_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(self.make_settings(Path(tmp)))
            job = manager.create_job("ashare", ["000001"], "2025-01-01", "2025-01-02", [], [], "zip")
            result = manager.cancel_job(job.id)
            self.assertEqual(result["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()


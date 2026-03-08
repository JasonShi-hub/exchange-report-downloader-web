from __future__ import annotations

import json
import queue
import shutil
import threading
import time
import uuid
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .downloaders.cninfo_downloader import CATEGORY_MAP as ASHARE_CATEGORY_MAP
from .downloaders.cninfo_downloader import CninfoDownloader
from .downloaders.hkex_downloader import HKEX_CATEGORY_MAP
from .downloaders.hkex_downloader import HKEXDownloader
from .settings import Settings

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}


class JobError(RuntimeError):
    pass


class JobQueueFullError(JobError):
    pass


class JobNotFoundError(JobError):
    pass


class JobStateError(JobError):
    pass


@dataclass
class Job:
    id: str
    market: str
    stocks: list[str]
    start_date: str
    end_date: str
    categories: list[str]
    languages: list[str]
    delivery_mode: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    expires_at: float | None = None
    error_message: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    stats: dict[str, int] = field(default_factory=lambda: {
        "total": 0,
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
    })
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    subscribers: list[queue.Queue] = field(default_factory=list)
    cancel_requested: bool = False
    work_dir: Path | None = None
    artifact_path: Path | None = None
    downloader: Any = None

    def as_dict(self, queue_position: int | None = None) -> dict[str, Any]:
        return {
            "jobId": self.id,
            "market": self.market,
            "stocks": self.stocks,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "categories": self.categories,
            "languages": self.languages,
            "deliveryMode": self.delivery_mode,
            "status": self.status,
            "queuePosition": queue_position,
            "createdAt": _iso_ts(self.created_at),
            "startedAt": _iso_ts(self.started_at),
            "finishedAt": _iso_ts(self.finished_at),
            "expiresAt": _iso_ts(self.expires_at),
            "progress": {
                "current": self.progress_current,
                "total": self.progress_total,
            },
            "stats": self.stats,
            "errorMessage": self.error_message,
            "artifactReady": bool(self.artifact_path and self.status == "completed"),
        }


def _iso_ts(timestamp: float | None) -> str | None:
    if not timestamp:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


class RateLimiter:
    def __init__(self, limit_per_minute: int):
        self.limit_per_minute = limit_per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= self.limit_per_minute:
                return False
            bucket.append(now)
            return True


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs: dict[str, Job] = {}
        self.queue: deque[str] = deque()
        self.current_job_id: str | None = None
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._worker_started = False
        self._login_limiter = RateLimiter(settings.login_rate_limit_per_minute)
        self._job_limiter = RateLimiter(settings.job_rate_limit_per_minute)

    def start(self) -> None:
        with self._lock:
            if self._worker_started:
                return
            self.settings.jobs_root.mkdir(parents=True, exist_ok=True)
            threading.Thread(target=self._worker_loop, daemon=True, name="job-worker").start()
            threading.Thread(target=self._cleanup_loop, daemon=True, name="job-cleaner").start()
            self._worker_started = True

    def allow_login(self, client_id: str) -> bool:
        return self._login_limiter.allow(client_id)

    def allow_job_create(self, client_id: str) -> bool:
        return self._job_limiter.allow(client_id)

    def create_job(
        self,
        market: str,
        stocks: list[str],
        start_date: str,
        end_date: str,
        categories: list[str],
        languages: list[str],
        delivery_mode: str,
    ) -> Job:
        with self._condition:
            if len(self.queue) >= self.settings.max_queued_jobs:
                raise JobQueueFullError("当前排队任务已满，请稍后再试")

            job = Job(
                id=uuid.uuid4().hex,
                market=market,
                stocks=stocks,
                start_date=start_date,
                end_date=end_date,
                categories=categories,
                languages=languages,
                delivery_mode=delivery_mode,
            )
            self.jobs[job.id] = job
            self.queue.append(job.id)
            self._publish(job, {"type": "state", "job": job.as_dict(queue_position=self._queue_position(job.id))})
            self._condition.notify_all()
            return job

    def get_job(self, job_id: str) -> Job:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                raise JobNotFoundError("任务不存在")
            return job

    def get_job_snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get_job(job_id)
            return job.as_dict(queue_position=self._queue_position(job_id))

    def subscribe(self, job_id: str) -> queue.Queue:
        with self._lock:
            job = self.get_job(job_id)
            subscriber: queue.Queue = queue.Queue()
            job.subscribers.append(subscriber)
            subscriber.put({
                "type": "snapshot",
                "job": job.as_dict(queue_position=self._queue_position(job_id)),
                "logs": list(job.logs),
            })
            if job.status in TERMINAL_STATUSES:
                subscriber.put({"type": "done", "job": job.as_dict(queue_position=None)})
            return subscriber

    def unsubscribe(self, job_id: str, subscriber: queue.Queue) -> None:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            if subscriber in job.subscribers:
                job.subscribers.remove(subscriber)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._condition:
            job = self.get_job(job_id)
            if job.status == "queued":
                try:
                    self.queue.remove(job_id)
                except ValueError:
                    pass
                job.status = "cancelled"
                job.finished_at = time.time()
                job.expires_at = job.finished_at + self.settings.job_retention_seconds
                self._publish(job, {"type": "log", "text": "[停止] 任务已在队列中取消"})
                self._publish_terminal(job)
                return job.as_dict()

            if job.status == "running":
                job.cancel_requested = True
                if job.downloader is not None:
                    job.downloader.stop_requested = True
                self._publish(job, {"type": "log", "text": "[停止] 正在尝试取消任务..."})
                return job.as_dict()

            if job.status in TERMINAL_STATUSES:
                raise JobStateError("任务已结束，无法取消")

            raise JobStateError("任务当前状态不允许取消")

    def stream_events(self, job_id: str):
        subscriber = self.subscribe(job_id)
        try:
            while True:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            self.unsubscribe(job_id, subscriber)

    def _queue_position(self, job_id: str) -> int | None:
        try:
            return list(self.queue).index(job_id) + 1
        except ValueError:
            return None

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self.queue:
                    self._condition.wait(timeout=1)
                job_id = self.queue.popleft()
                job = self.jobs[job_id]
                self.current_job_id = job_id
                job.status = "running"
                job.started_at = time.time()
                self._publish(job, {"type": "state", "job": job.as_dict(queue_position=None)})

            try:
                self._execute_job(job)
            finally:
                with self._condition:
                    self.current_job_id = None
                    self._condition.notify_all()

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(60)
            now = time.time()
            expired: list[Job] = []
            with self._lock:
                for job in self.jobs.values():
                    if job.status in {"running", "queued"}:
                        continue
                    if not job.expires_at or job.expires_at > now or job.status == "expired":
                        continue
                    expired.append(job)

            for job in expired:
                if job.work_dir and job.work_dir.exists():
                    shutil.rmtree(job.work_dir, ignore_errors=True)
                with self._lock:
                    job.status = "expired"
                    job.artifact_path = None
                    self._publish(job, {"type": "state", "job": job.as_dict(queue_position=None)})

    def _execute_job(self, job: Job) -> None:
        work_dir = self.settings.jobs_root / job.id
        output_dir = work_dir / "downloads"
        market_dir = output_dir / ("A股" if job.market == "ashare" else "港股")
        work_dir.mkdir(parents=True, exist_ok=True)
        market_dir.mkdir(parents=True, exist_ok=True)
        job.work_dir = work_dir

        def on_message(message: str, **kwargs: Any) -> None:
            self._publish(job, {"type": "log", "text": message})
            if "progress" in kwargs and "total" in kwargs:
                job.progress_current = int(kwargs["progress"] or 0)
                job.progress_total = int(kwargs["total"] or 0)
                self._publish(job, {
                    "type": "progress",
                    "current": job.progress_current,
                    "total": job.progress_total,
                })
            if kwargs.get("done"):
                job.stats = kwargs.get("stats") or job.stats
                self._publish(job, {"type": "stats", "stats": job.stats})

        try:
            if job.market == "ashare":
                category_codes = [ASHARE_CATEGORY_MAP[item] for item in job.categories if item in ASHARE_CATEGORY_MAP]
                downloader = CninfoDownloader(output_dir=str(market_dir), on_message=on_message)
                job.downloader = downloader
                for stock_code in job.stocks:
                    if job.cancel_requested:
                        downloader.stop_requested = True
                        break
                    downloader.process_stock(stock_code, job.start_date, job.end_date, category_codes or None)
                downloader.print_summary()
            else:
                category_codes = [item for item in job.categories if item in HKEX_CATEGORY_MAP]
                languages = [item for item in job.languages if item in {"中文", "英文"}] or None
                downloader = HKEXDownloader(output_dir=str(market_dir), on_message=on_message)
                job.downloader = downloader
                for stock_code in job.stocks:
                    if job.cancel_requested:
                        downloader.stop_requested = True
                        break
                    downloader.process_stock(stock_code, job.start_date, job.end_date, category_codes or None, languages)
                downloader.print_summary()

            finished_at = time.time()
            job.finished_at = finished_at
            job.expires_at = finished_at + self.settings.job_retention_seconds

            if job.cancel_requested or (job.downloader and job.downloader.stop_requested):
                job.status = "cancelled"
            else:
                job.status = "completed"
                job.artifact_path = self._build_zip_artifact(job, output_dir)
        except Exception as exc:  # pragma: no cover - defensive path
            job.status = "failed"
            job.finished_at = time.time()
            job.expires_at = job.finished_at + self.settings.job_retention_seconds
            job.error_message = str(exc)
            self._publish(job, {"type": "log", "text": f"[错误] 任务异常: {exc}"})
        finally:
            job.downloader = None
            self._publish_terminal(job)

    def _build_zip_artifact(self, job: Job, output_dir: Path) -> Path:
        artifact_path = job.work_dir / f"exchange-report-{job.id}.zip"
        with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            files_found = False
            for file_path in sorted(output_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                files_found = True
                zf.write(file_path, arcname=file_path.relative_to(output_dir))
            if not files_found:
                zf.writestr("README.txt", "任务已完成，但没有可打包的文件。")
        return artifact_path

    def _publish_terminal(self, job: Job) -> None:
        self._publish(job, {"type": "state", "job": job.as_dict(queue_position=None)})
        self._publish(job, {"type": "done", "job": job.as_dict(queue_position=None)})

    def _publish(self, job: Job, event: dict[str, Any]) -> None:
        if event.get("type") == "log" and event.get("text"):
            job.logs.append(str(event["text"]))
        subscribers = list(job.subscribers)
        for subscriber in subscribers:
            subscriber.put(event)


from __future__ import annotations

from datetime import datetime
import hmac
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .downloaders.cninfo_downloader import CATEGORY_MAP as ASHARE_CATEGORY_MAP
from .downloaders.hkex_downloader import HKEX_CATEGORY_MAP
from .job_manager import JobManager, JobNotFoundError, JobQueueFullError, JobStateError
from .security import TokenError, issue_token, verify_token
from .settings import Settings, load_settings

settings = load_settings()
manager = JobManager(settings)

app = FastAPI(title="Exchange Report Downloader API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def on_startup() -> None:
    manager.start()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _validate_token(authorization: str = Header(default="")) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少有效的访问令牌")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_token(settings.token_secret, token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式错误: {date_str}") from exc


def _validate_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    market = str(payload.get("market", "")).strip()
    stocks = [str(item).strip() for item in payload.get("stocks", []) if str(item).strip()]
    start_date = str(payload.get("startDate", "")).strip()
    end_date = str(payload.get("endDate", "")).strip()
    categories = [str(item).strip() for item in payload.get("categories", []) if str(item).strip()]
    languages = [str(item).strip() for item in payload.get("languages", []) if str(item).strip()]
    delivery_mode = str(payload.get("deliveryMode", "zip")).strip() or "zip"

    if market not in {"ashare", "hkex"}:
        raise HTTPException(status_code=422, detail="market 仅支持 ashare 或 hkex")
    if not stocks:
        raise HTTPException(status_code=422, detail="至少输入一个股票代码")
    if len(stocks) > settings.max_stocks_per_job:
        raise HTTPException(
            status_code=422,
            detail=f"单次最多 {settings.max_stocks_per_job} 个股票代码",
        )

    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    if end_dt < start_dt:
        raise HTTPException(status_code=422, detail="结束日期不能早于起始日期")
    if (end_dt - start_dt).days > settings.max_date_range_days:
        raise HTTPException(
            status_code=422,
            detail=f"日期范围不能超过 {settings.max_date_range_days} 天",
        )

    if market == "ashare":
        invalid = [item for item in categories if item not in ASHARE_CATEGORY_MAP]
        if invalid:
            raise HTTPException(status_code=422, detail=f"A股类别无效: {', '.join(invalid)}")
        languages = []
    else:
        invalid = [item for item in categories if item not in HKEX_CATEGORY_MAP]
        if invalid:
            raise HTTPException(status_code=422, detail=f"港股类别无效: {', '.join(invalid)}")
        invalid_langs = [item for item in languages if item not in {"中文", "英文"}]
        if invalid_langs:
            raise HTTPException(status_code=422, detail=f"语言无效: {', '.join(invalid_langs)}")

    if delivery_mode not in {"zip", "folder"}:
        raise HTTPException(status_code=422, detail="deliveryMode 仅支持 zip 或 folder")

    return {
        "market": market,
        "stocks": stocks,
        "start_date": start_date,
        "end_date": end_date,
        "categories": categories,
        "languages": languages,
        "delivery_mode": delivery_mode,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
async def login(request: Request) -> dict[str, Any]:
    if not settings.access_password:
        raise HTTPException(status_code=503, detail="服务端尚未配置 ACCESS_PASSWORD")

    client_ip = _client_ip(request)
    if not manager.allow_login(client_ip):
        raise HTTPException(status_code=429, detail="登录过于频繁，请稍后再试")

    payload = await request.json()
    password = str(payload.get("password", "")).strip()
    if not hmac.compare_digest(password, settings.access_password):
        raise HTTPException(status_code=401, detail="密码错误")

    token, expires_at = issue_token(settings.token_secret, "shared-access", settings.token_ttl_seconds)
    return {
        "token": token,
        "tokenType": "Bearer",
        "expiresAt": datetime.utcfromtimestamp(expires_at).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.post("/api/auth/logout")
def logout(_: dict[str, Any] = Depends(_validate_token)) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta")
def meta(_: dict[str, Any] = Depends(_validate_token)) -> dict[str, Any]:
    return {
        "frontEndDomain": settings.allowed_origin,
        "defaults": {
            "market": "ashare",
            "deliveryMode": "zip",
        },
        "limits": {
            "maxStocksPerJob": settings.max_stocks_per_job,
            "maxDateRangeDays": settings.max_date_range_days,
            "maxQueuedJobs": settings.max_queued_jobs,
            "artifactRetentionSeconds": settings.job_retention_seconds,
        },
        "categories": {
            "ashare": list(ASHARE_CATEGORY_MAP.keys()),
            "hkex": list(HKEX_CATEGORY_MAP.keys()),
        },
        "languages": ["中文", "英文"],
        "presets": {
            "asharePeriodic": ["年报", "半年报", "一季报", "三季报"],
            "hkexResultsOnly": ["年度业绩", "中期业绩", "季度业绩", "年度报告"],
        },
        "notes": {
            "ashareEmptyCategories": "A股不勾选类别时下载全部常规公告（不含调研）",
            "hkexEmptyCategories": "港股不勾选类别时下载全部公告",
        },
    }


@app.post("/api/jobs")
async def create_job(request: Request, _: dict[str, Any] = Depends(_validate_token)) -> dict[str, Any]:
    client_ip = _client_ip(request)
    if not manager.allow_job_create(client_ip):
        raise HTTPException(status_code=429, detail="创建任务过于频繁，请稍后再试")

    payload = _validate_job_payload(await request.json())
    try:
        job = manager.create_job(**payload)
    except JobQueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"job": job.as_dict(queue_position=manager._queue_position(job.id))}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, _: dict[str, Any] = Depends(_validate_token)) -> dict[str, Any]:
    try:
        return {"job": manager.get_job_snapshot(job_id)}
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str, _: dict[str, Any] = Depends(_validate_token)):
    try:
        manager.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return StreamingResponse(
        manager.stream_events(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, _: dict[str, Any] = Depends(_validate_token)) -> dict[str, Any]:
    try:
        return {"job": manager.cancel_job(job_id)}
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/artifact")
def download_artifact(job_id: str, _: dict[str, Any] = Depends(_validate_token)):
    try:
        job = manager.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.status == "expired":
        raise HTTPException(status_code=410, detail="任务结果已过期")
    if job.status != "completed" or not job.artifact_path or not Path(job.artifact_path).exists():
        raise HTTPException(status_code=409, detail="任务尚未生成可下载结果")

    return FileResponse(
        path=job.artifact_path,
        media_type="application/zip",
        filename=f"exchange-report-{job_id}.zip",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

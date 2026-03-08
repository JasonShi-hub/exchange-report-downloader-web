from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class TokenError(ValueError):
    pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def issue_token(secret: str, subject: str, ttl_seconds: int) -> tuple[str, int]:
    expires_at = int(time.time()) + ttl_seconds
    payload = {"sub": subject, "exp": expires_at}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(payload_bytes)
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64encode(signature)}", expires_at


def verify_token(secret: str, token: str) -> dict[str, Any]:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("令牌格式错误") from exc

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual_sig = _b64decode(signature_part)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenError("令牌签名无效")

    try:
        payload = json.loads(_b64decode(payload_part).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TokenError("令牌载荷无效") from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("令牌已过期")
    return payload


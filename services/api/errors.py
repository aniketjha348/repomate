"""Typed HTTP errors — clients never see stack traces."""

from __future__ import annotations

from fastapi import HTTPException

from repomate_core.contracts import ErrorCode

_STATUS_BY_CODE = {
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.UNSUPPORTED_INPUT: 422,
    ErrorCode.RATE_LIMITED: 429,
}


def api_error(status_code: int, code: ErrorCode, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code.value, "message": message},
    )


def status_for(code: ErrorCode) -> int:
    return _STATUS_BY_CODE.get(code, 400)

"""Pydantic models for API I/O."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as UTC ISO with explicit offset.

    SQLite strips tzinfo on round-trip, so values stored via models.utcnow()
    come back naive. Without an explicit offset the browser would parse the
    string as local time and skew the display by the local UTC offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_admin: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_filename: str
    source_kind: str
    mode: Literal["full", "text-only"]
    status: Literal["queued", "running", "done", "failed", "canceled"]
    page_count: int
    current_page: int
    progress_pct: int
    duration_seconds: int
    error_msg: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    queue_position: int = 0
    eta_seconds: int = 0

    @field_serializer("created_at", "started_at", "finished_at")
    def _serialize_dt(self, dt: datetime | None) -> str | None:
        return _utc_iso(dt)


class JobLogOut(BaseModel):
    id: str
    log_tail: str


class VersionOut(BaseModel):
    commit: str
    short_commit: str
    behind: int
    ahead: int
    branch: str
    remote_url: str
    auto_update: bool
    updating: bool
    last_check: datetime | None
    sandbox_backend: str = "none"
    sandbox_allow_network: bool = True

    @field_serializer("last_check")
    def _serialize_dt(self, dt: datetime | None) -> str | None:
        return _utc_iso(dt)


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False

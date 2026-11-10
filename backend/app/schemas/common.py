from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadyResponse(HealthResponse):
    database: dict[str, str]


class PageResponse(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None
    has_more: bool = False


class ApiError(BaseModel):
    detail: str


class QueryParams(BaseModel):
    inicio: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    fim: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    metodologia: str = "Novo Caged - sem ajuste"

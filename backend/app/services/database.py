from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, text

from banco.conexao import criar_engine, verificar_conexao
from banco.consultas import ConsultasEmprego

from app.core.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return criar_engine(settings.database_url, pool_size=5, max_overflow=5)


def get_consultas() -> ConsultasEmprego:
    return ConsultasEmprego(get_engine(), settings.uf, settings.cod_uf)


def database_status() -> dict[str, str]:
    return verificar_conexao(get_engine(), tentativas=1)


def listar_municipios(cursor: str | None, limite: int) -> tuple[list[dict[str, Any]], str | None]:
    query = """
        SELECT cod_ibge, nome, uf, capital, area_km2
        FROM vw_municipios_validados
        WHERE uf = :uf AND (CAST(:cursor AS text) IS NULL OR cod_ibge > CAST(:cursor AS text))
        ORDER BY cod_ibge
        LIMIT :limite
    """
    with get_engine().connect() as connection:
        rows = [dict(row) for row in connection.execute(text(query), {
            "uf": settings.uf,
            "cursor": cursor,
            "limite": limite + 1,
        }).mappings()]
    has_more = len(rows) > limite
    rows = rows[:limite]
    return rows, (rows[-1]["cod_ibge"] if has_more and rows else None)

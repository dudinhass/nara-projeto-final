from __future__ import annotations

from typing import Any, Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy.exc import SQLAlchemyError

from banco.conexao import ErroConexaoBanco
from banco.consultas import COLUNAS_RANKING, ErroConsulta

from app.core.config import settings
from app.schemas.common import HealthResponse, PageResponse, ReadyResponse
from app.services.database import database_status, get_consultas, listar_municipios

router = APIRouter()


def _run(call):  # noqa: ANN001
    try:
        return call()
    except ErroConsulta as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ErroConexaoBanco, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc


@router.get("/health/live", response_model=HealthResponse, tags=["saúde"])
def live() -> HealthResponse:
    return HealthResponse(status="ok", service="emprego-maranhao-api", version=settings.api_version)


@router.get("/health/ready", response_model=ReadyResponse, tags=["saúde"])
def ready() -> ReadyResponse:
    database = _run(database_status)
    return ReadyResponse(status="ok", service="emprego-maranhao-api", version=settings.api_version, database=database)


@router.get("/meta", tags=["saúde"])
def meta() -> dict[str, Any]:
    return {
        "uf": settings.uf,
        "codigo_uf": settings.cod_uf,
        "fonte": "IpeaData",
        "metodologia_padrao": settings.metodologia_padrao,
        "regra_procedencia": "Somente dados com procedência validada no IpeaData são exibidos.",
        "regra_lacunas": "Meses sem observação permanecem nulos e são marcados como sem_observacao.",
    }


@router.get("/municipios", response_model=PageResponse, tags=["municípios"])
def municipios(
    cursor: Annotated[str | None, Query(pattern=r"^\d{7}$")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PageResponse:
    items, next_cursor = _run(lambda: listar_municipios(cursor, limite))
    return PageResponse(items=items, next_cursor=next_cursor, has_more=next_cursor is not None)


@router.get("/municipios/{cod_ibge}/historico", tags=["municípios"])
def historico_municipio(cod_ibge: Annotated[str, Path(pattern=r"^\d{7}$")], metodologia: str = settings.metodologia_padrao) -> dict[str, Any]:
    return _run(lambda: get_consultas().historico_municipio(cod_ibge, metodologia))


@router.get("/municipios/{cod_ibge}/mensal", tags=["séries"])
def mensal(
    cod_ibge: Annotated[str, Path(pattern=r"^\d{7}$")],
    inicio: str | None = None,
    fim: str | None = None,
    metodologia: str = settings.metodologia_padrao,
) -> list[dict[str, Any]]:
    return _run(lambda: get_consultas().evolucao_mensal(cod_ibge, inicio, fim, metodologia))


@router.get("/municipios/{cod_ibge}/anual", tags=["séries"])
def anual(cod_ibge: Annotated[str, Path(pattern=r"^\d{7}$")], metodologia: str = settings.metodologia_padrao) -> list[dict[str, Any]]:
    return _run(lambda: get_consultas().evolucao_anual(cod_ibge, metodologia))


@router.get("/ranking", tags=["análises"])
def ranking(
    indicador: Literal["admissoes", "desligamentos", "saldo"] = "saldo",
    inicio: str | None = None,
    fim: str | None = None,
    ordem: str = Query("desc", pattern=r"^(asc|desc)$"),
    limite: Annotated[int, Query(ge=1, le=100)] = 10,
    metodologia: str = settings.metodologia_padrao,
) -> list[dict[str, Any]]:
    return _run(lambda: get_consultas().ranking_municipios(indicador, inicio, fim, limite, ordem, metodologia))


@router.get("/totais/uf", tags=["análises"])
def totais_uf(inicio: str | None = None, fim: str | None = None, metodologia: str = settings.metodologia_padrao) -> dict[str, Any]:
    return _run(lambda: get_consultas().totais_uf(inicio, fim, metodologia))


@router.get("/indicadores", tags=["análises"])
def indicadores(inicio: str | None = None, fim: str | None = None, metodologia: str = settings.metodologia_padrao) -> dict[str, Any]:
    return _run(lambda: get_consultas().indicadores_periodo(inicio, fim, metodologia))


@router.get("/cobertura", tags=["análises"])
def cobertura() -> list[dict[str, Any]]:
    return _run(lambda: get_consultas().cobertura_series())


@router.get("/comparar-periodos", tags=["análises"])
def comparar_periodos(
    inicio_a: str,
    fim_a: str,
    inicio_b: str,
    fim_b: str,
    cod_ibge: Annotated[str | None, Query(pattern=r"^\d{7}$")] = None,
    metodologia: str = settings.metodologia_padrao,
) -> dict[str, Any]:
    return _run(lambda: get_consultas().comparar_periodos((inicio_a, fim_a), (inicio_b, fim_b), cod_ibge, metodologia))

"""Matrizes de cobertura: município × mês e município × ano × indicador.

Distingue, para cada combinação:

1. ``zero_encontrado``: observação publicada com valor zero;
2. ``observacao_ausente``: período coberto pela série, sem registro;
3. ``nao_disponibilizado_pela_fonte``: período fora da disponibilidade da série;
4. ``falha_coleta``: a coleta falhou e não há dados para verificar.

Os meses esperados de cada ano vêm da disponibilidade efetiva da série
(primeiro e último mês publicados no nível municipal), não de um intervalo fixo.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

import pandas as pd

INDICADORES = ("admissoes", "desligamentos")
COLUNAS_MENSAL = [
    "codigo_ibge", "municipio", "data_referencia", "ano", "mes", "indicador", "fonte", "serie_codigo",
    "metodologia", "valor", "status", "lacuna_sistemica_fonte",
]
COLUNAS_ANUAL = [
    "codigo_ibge", "municipio", "ano", "indicador", "fonte", "serie_codigo", "metodologia",
    "meses_esperados", "meses_encontrados", "meses_valor_zero", "meses_ausentes",
    "meses_lacuna_sistemica_fonte", "meses_ausentes_lista", "status_cobertura",
]


def matriz_mensal(painel: pd.DataFrame, lacunas_sistemicas: dict[str, set[date]]) -> pd.DataFrame:
    """Formato longo do painel: uma linha por município × mês × indicador."""
    partes = []
    for indicador in INDICADORES:
        parte = pd.DataFrame(
            {
                "codigo_ibge": painel["cod_ibge"],
                "municipio": painel["municipio"],
                "data_referencia": painel["data_referencia"],
                "ano": painel["ano"],
                "mes": painel["mes"],
                "indicador": indicador,
                "fonte": painel["fonte"],
                "serie_codigo": painel[f"serie_{indicador}"],
                "metodologia": painel["metodologia"],
                "valor": painel[indicador],
                "status": painel[f"status_{indicador}"],
            }
        )
        lacunas = lacunas_sistemicas.get(indicador, set())
        parte["lacuna_sistemica_fonte"] = (parte["status"] == "observacao_ausente") & parte[
            "data_referencia"
        ].dt.date.isin(lacunas)
        partes.append(parte)
    return pd.concat(partes, ignore_index=True)[COLUNAS_MENSAL]


def _status_anual(linha: pd.Series) -> str:
    if linha["meses_falha"] > 0:
        return "falha_coleta"
    if linha["meses_esperados"] == 0:
        return "nao_disponibilizado_pela_fonte"
    if linha["meses_encontrados"] == linha["meses_esperados"]:
        return "completo"
    if linha["meses_encontrados"] == 0:
        return "sem_registros"
    return "incompleto"


def matriz_anual(
    mensal: pd.DataFrame,
    municipios: pd.DataFrame,
    anos: Iterable[int],
    series: dict[str, dict[str, str]],
) -> pd.DataFrame:
    """Agrega a matriz mensal por ano e completa os anos sem disponibilidade.

    ``series`` mapeia indicador -> {"serie_codigo", "metodologia", "fonte"}.
    """
    m = mensal.assign(
        esperado=~mensal["status"].isin(["nao_disponibilizado_pela_fonte", "falha_coleta"]),
        encontrado=mensal["status"].isin(["valor_encontrado", "zero_encontrado"]),
        zero=mensal["status"] == "zero_encontrado",
        ausente=mensal["status"] == "observacao_ausente",
        falha=mensal["status"] == "falha_coleta",
        mes_ausente=lambda d: d["data_referencia"].dt.strftime("%Y-%m").where(d["status"] == "observacao_ausente"),
    )
    agregado = (
        m.groupby(["codigo_ibge", "ano", "indicador"])
        .agg(
            meses_esperados=("esperado", "sum"),
            meses_encontrados=("encontrado", "sum"),
            meses_valor_zero=("zero", "sum"),
            meses_ausentes=("ausente", "sum"),
            meses_lacuna_sistemica_fonte=("lacuna_sistemica_fonte", "sum"),
            meses_falha=("falha", "sum"),
            meses_ausentes_lista=("mes_ausente", lambda s: ";".join(sorted(s.dropna()))),
        )
        .reset_index()
    )

    grade = pd.MultiIndex.from_product(
        [municipios["cod_ibge"].tolist(), sorted(set(anos)), list(series)],
        names=["codigo_ibge", "ano", "indicador"],
    ).to_frame(index=False)
    anual = grade.merge(agregado, on=["codigo_ibge", "ano", "indicador"], how="left")
    contagens = ["meses_esperados", "meses_encontrados", "meses_valor_zero", "meses_ausentes",
                 "meses_lacuna_sistemica_fonte", "meses_falha"]
    anual[contagens] = anual[contagens].fillna(0).astype(int)
    anual["meses_ausentes_lista"] = anual["meses_ausentes_lista"].fillna("")
    anual = anual.merge(
        municipios[["cod_ibge", "municipio"]].rename(columns={"cod_ibge": "codigo_ibge"}), on="codigo_ibge", how="left"
    )
    for campo in ("fonte", "serie_codigo", "metodologia"):
        anual[campo] = anual["indicador"].map({ind: info[campo] for ind, info in series.items()})
    anual["status_cobertura"] = anual.apply(_status_anual, axis=1)
    return anual.sort_values(["codigo_ibge", "ano", "indicador"]).reset_index(drop=True)[COLUNAS_ANUAL]


def resumo(mensal: pd.DataFrame, anual: pd.DataFrame, municipios: pd.DataFrame) -> dict[str, Any]:
    por_indicador = {}
    for indicador, parte in mensal.groupby("indicador"):
        encontrados = parte[parte["status"].isin(["valor_encontrado", "zero_encontrado"])]
        anos_com_dados = sorted(encontrados["ano"].dropna().astype(int).unique().tolist())
        com_dados = set(encontrados["codigo_ibge"])
        ausentes = parte[parte["status"] == "observacao_ausente"]
        por_indicador[indicador] = {
            "situacao_mensal": parte["status"].value_counts().to_dict(),
            "municipios_com_dados": len(com_dados),
            "municipios_sem_dados": sorted(set(municipios["cod_ibge"]) - com_dados),
            "primeiro_ano": anos_com_dados[0] if anos_com_dados else None,
            "ultimo_ano": anos_com_dados[-1] if anos_com_dados else None,
            "anos_com_dados": len(anos_com_dados),
            "primeiro_mes": encontrados["data_referencia"].min().date().isoformat() if len(encontrados) else None,
            "ultimo_mes": encontrados["data_referencia"].max().date().isoformat() if len(encontrados) else None,
            "observacoes_ausentes": [
                {"codigo_ibge": c, "municipio": n, "mes": d.date().isoformat(), "lacuna_sistemica_fonte": bool(s)}
                for c, n, d, s in ausentes[["codigo_ibge", "municipio", "data_referencia", "lacuna_sistemica_fonte"]]
                .itertuples(index=False)
            ],
            "situacao_anual": anual[anual["indicador"] == indicador]["status_cobertura"].value_counts().to_dict(),
        }
    return {"municipios_oficiais": int(municipios["cod_ibge"].nunique()), "por_indicador": por_indicador}

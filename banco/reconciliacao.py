"""Reconciliação: arquivos processados da coleta × conteúdo do PostgreSQL.

Por série e ano compara quantidade, soma e um hash MD5 do conteúdo
(nível|território|data|valor, ordenado byte a byte), calculado do mesmo jeito
nos dois lados. Grupos com hash diferente são detalhados chave a chave.
Também confere o cadastro de municípios e a contagem por município.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

from coleta import esquema
from coleta.config import SERIES, Diretorios
from coleta.repositorio import RepositorioDados

SQL_GRUPOS = """
SELECT s.codigo AS serie, r.ano, count(*) AS linhas, sum(r.valor) AS soma,
       min(r.data_referencia) AS inicio, max(r.data_referencia) AS fim,
       md5(string_agg(
           r.nivel_territorial || '|' || r.cod_territorio || '|' || to_char(r.data_referencia, 'YYYY-MM-DD') || '|' || r.valor,
           E'\\n' ORDER BY r.nivel_territorial COLLATE "C", r.cod_territorio COLLATE "C", r.data_referencia
       )) AS md5
FROM registros_emprego r JOIN series_indicadores s ON s.id = r.serie_id
GROUP BY s.codigo, r.ano
"""


def chave_territorio(df: pd.DataFrame) -> pd.Series:
    """Mesma normalização do importador: Brasil vira 'BR'; município e UF usam o código IBGE."""
    return df["cod_ibge"].where(df["nivel_territorial"] != "brasil", "BR")


def linhas_canonicas(df: pd.DataFrame) -> list[str]:
    tabela = pd.DataFrame({
        "nivel": df["nivel_territorial"].astype(str), "cod": chave_territorio(df).astype(str),
        "data": df["data_referencia"].dt.strftime("%Y-%m-%d"), "valor": df["valor"].astype("Int64").astype(str),
    }).sort_values(["nivel", "cod", "data"])
    return ("|".join(t) for t in tabela.itertuples(index=False, name=None))  # type: ignore[return-value]


def md5_linhas(df: pd.DataFrame) -> str:
    return hashlib.md5("\n".join(linhas_canonicas(df)).encode("utf-8")).hexdigest()


def grupos_origem(dirs: Diretorios) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    repo = RepositorioDados(dirs)
    linhas, bases = [], {}
    for serie in SERIES.values():
        df = repo.ler(serie)
        bases[serie.codigo] = df
        for ano, parte in df.groupby("ano"):
            linhas.append({
                "serie": serie.codigo, "ano": int(ano), "linhas": len(parte), "soma": int(parte["valor"].sum()),
                "inicio": parte["data_referencia"].min().date(), "fim": parte["data_referencia"].max().date(),
                "md5": md5_linhas(parte),
            })
    return pd.DataFrame(linhas), bases


def _detalhar(engine: Engine, serie: str, ano: int, origem: pd.DataFrame) -> dict[str, Any]:
    with engine.connect() as con:
        banco = pd.read_sql(text(
            "SELECT r.nivel_territorial, r.cod_territorio AS cod, r.data_referencia, r.valor "
            "FROM registros_emprego r JOIN series_indicadores s ON s.id = r.serie_id WHERE s.codigo = :s AND r.ano = :a"
        ), con, params={"s": serie, "a": ano})
    o = origem[origem["ano"] == ano].assign(cod=lambda d: chave_territorio(d))[
        ["nivel_territorial", "cod", "data_referencia", "valor"]]
    banco["data_referencia"] = pd.to_datetime(banco["data_referencia"])
    comb = o.merge(banco, on=["nivel_territorial", "cod", "data_referencia"], how="outer",
                   suffixes=("_origem", "_banco"), indicator=True)
    so_origem = comb[comb["_merge"] == "left_only"]
    so_banco = comb[comb["_merge"] == "right_only"]
    diferentes = comb[(comb["_merge"] == "both") & (comb["valor_origem"] != comb["valor_banco"])]
    exemplo = lambda d: d.head(10).astype(str).to_dict("records")  # noqa: E731
    return {"serie": serie, "ano": ano, "somente_na_origem": len(so_origem), "somente_no_banco": len(so_banco),
            "valores_diferentes": len(diferentes), "exemplos": exemplo(pd.concat([so_origem, so_banco, diferentes]))}


def reconciliar(engine: Engine, dirs: Diretorios, uf: str = "MA") -> dict[str, Any]:
    origem, bases = grupos_origem(dirs)
    with engine.connect() as con:
        banco = pd.read_sql(text(SQL_GRUPOS), con)
        municipios_banco = pd.read_sql(text("SELECT cod_ibge, nome FROM municipios WHERE uf = :uf"), con, params={"uf": uf})
        obs_municipio = pd.read_sql(text(
            "SELECT s.codigo AS serie, r.municipio_cod AS cod_ibge, count(*) AS linhas FROM registros_emprego r "
            "JOIN series_indicadores s ON s.id = r.serie_id WHERE r.nivel_territorial = 'municipio' GROUP BY 1, 2"
        ), con)
        duplicadas = con.execute(text(
            "SELECT count(*) FROM (SELECT 1 FROM registros_emprego GROUP BY serie_id, nivel_territorial, "
            "cod_territorio, data_referencia HAVING count(*) > 1) d"
        )).scalar_one()
    banco["soma"] = banco["soma"].astype("int64")
    comp = origem.merge(banco, on=["serie", "ano"], how="outer", suffixes=("_origem", "_banco"), indicator=True)
    comp["confere"] = (comp["_merge"] == "both") & (comp["linhas_origem"] == comp["linhas_banco"]) & \
        (comp["soma_origem"] == comp["soma_banco"]) & (comp["md5_origem"] == comp["md5_banco"])
    divergentes = comp[~comp["confere"]]
    detalhes = [_detalhar(engine, r.serie, int(r.ano), bases.get(r.serie, pd.DataFrame())) for r in divergentes.itertuples()
                if r.serie in bases]

    municipios_origem = esquema.ler_csv(dirs.consolidado / "municipios.csv", esquema.MUNICIPIO)
    por_serie = comp.groupby("serie").agg(
        linhas_origem=("linhas_origem", "sum"), linhas_banco=("linhas_banco", "sum"),
        soma_origem=("soma_origem", "sum"), soma_banco=("soma_banco", "sum"),
        inicio=("inicio_origem", "min"), fim=("fim_origem", "max"), grupos_divergentes=("confere", lambda s: int((~s).sum())),
    ).reset_index()
    por_ano = comp.groupby("ano").agg(linhas_origem=("linhas_origem", "sum"), linhas_banco=("linhas_banco", "sum")).reset_index()
    contagem_municipal: dict[str, Any] = {}
    for codigo, df in bases.items():
        if SERIES[codigo].escopo != "municipal":
            continue
        o = df[df["nivel_territorial"] == "municipio"].groupby("cod_ibge").size()
        b = obs_municipio[obs_municipio["serie"] == codigo].set_index("cod_ibge")["linhas"]
        dif = o.subtract(b, fill_value=0)
        contagem_municipal[codigo] = {
            "municipios_com_observacoes_origem": int((o > 0).sum()), "municipios_com_observacoes_banco": int((b > 0).sum()),
            "municipios_com_contagem_diferente": dif[dif != 0].index.tolist(),
            "distribuicao_observacoes_por_municipio": {str(k): int(v) for k, v in b.value_counts().sort_index().items()},
        }

    conciliado = divergentes.empty and duplicadas == 0 and set(municipios_banco["cod_ibge"]) == set(municipios_origem["cod_ibge"]) \
        and all(not v["municipios_com_contagem_diferente"] for v in contagem_municipal.values())
    para_int = lambda df: df.astype(object).where(df.notna(), None).to_dict("records")  # noqa: E731
    return {
        "situacao": "conciliado" if conciliado else "divergente",
        "totais": {
            "linhas_origem": int(origem["linhas"].sum()), "linhas_banco": int(banco["linhas"].sum()),
            "soma_origem": int(origem["soma"].sum()), "soma_banco": int(banco["soma"].sum()),
            "grupos_serie_ano": int(len(comp)), "grupos_divergentes": int(len(divergentes)),
            "chaves_duplicadas_no_banco": int(duplicadas),
        },
        "municipios": {
            "cadastro_origem": int(len(municipios_origem)), "cadastro_banco": int(len(municipios_banco)),
            "somente_origem": sorted(set(municipios_origem["cod_ibge"]) - set(municipios_banco["cod_ibge"])),
            "somente_banco": sorted(set(municipios_banco["cod_ibge"]) - set(municipios_origem["cod_ibge"])),
        },
        "por_serie": para_int(por_serie),
        "por_ano": para_int(por_ano),
        "contagem_por_municipio": contagem_municipal,
        "divergencias": detalhes,
    }

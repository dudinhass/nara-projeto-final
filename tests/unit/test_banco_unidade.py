"""Partes da camada de banco testáveis sem servidor."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy.engine import make_url

from banco.consultas import ErroConsulta, competencia, ConsultasEmprego
from banco.importacao import ContextoValidacao, escopo_do_arquivo, validar_lote
from banco.reconciliacao import md5_linhas
from coleta import esquema
from coleta.config import ConfigBanco
from coleta.transformacao import ContextoSerie, processar
from coleta.config import SERIES
from tests.conftest import OFICIAIS, metadados, valor

SERIES_DB = {"ADMISNC": {"id": 1, "indicador": "admissoes", "metodologia": "Novo Caged - sem ajuste", "fonte": "IpeaData"}}


def observacoes(registros):
    ctx = ContextoSerie(SERIES["ADMISNC"], metadados("ADMISNC"), "MA", "21", dict(OFICIAIS), "2026-10-25T12:00:00+00:00",
                        "full-x", "data/raw/ipeadata/x.json.gz")
    return processar([registros], ctx).observacoes


def contexto(**mudancas):
    base = dict(series=SERIES_DB, municipios=set(OFICIAIS), cod_uf="21", arquivo="a.csv", serie_esperada="ADMISNC")
    return ContextoValidacao(**{**base, **mudancas})


def test_validar_lote_normaliza_territorio_e_proveniencia():
    df = observacoes([valor("ADMISNC", "2020-01-01", 7, "Municípios", "2111300"),
                      valor("ADMISNC", "2020-01-01", 9, "Estados", "21"),
                      valor("ADMISNC", "2020-01-01", 99, "Brasil", "0")])
    validos, rejeicoes = validar_lote(df, contexto())
    assert rejeicoes == []
    por_nivel = validos.set_index("nivel_territorial")
    assert por_nivel.loc["municipio", "cod_territorio"] == "2111300" and por_nivel.loc["municipio", "municipio_cod"] == "2111300"
    assert por_nivel.loc["estado", "cod_territorio"] == "21" and pd.isna(por_nivel.loc["estado", "municipio_cod"])
    assert por_nivel.loc["brasil", "cod_territorio"] == "BR" and pd.isna(por_nivel.loc["brasil", "uf"])
    assert por_nivel.loc["brasil", "cod_territorio_original"] == "0"
    assert set(validos["arquivo_processado"]) == {"a.csv"} and set(validos["serie_id"]) == {1}


def test_validar_lote_rejeita_com_motivo_sem_converter_em_zero():
    df = observacoes([valor("ADMISNC", m, 5, "Municípios", "2111300") for m in ("2020-01-01", "2020-02-01", "2020-03-01")])
    df.loc[0, "valor"] = pd.NA
    df.loc[1, "valor"] = -1
    df.loc[2, "metodologia"] = "CAGED tradicional"
    _, rejeicoes = validar_lote(df, contexto())
    assert [r["tipo"] for r in rejeicoes] == ["registro_rejeitado:valor_ausente", "registro_rejeitado:valor_negativo_em_contagem",
                                              "registro_rejeitado:metodologia_divergente"]


def test_validar_lote_rejeita_territorio_e_serie_inesperados():
    df = observacoes([valor("ADMISNC", "2020-01-01", 5, "Municípios", "2111300")])
    assert validar_lote(df, contexto(municipios={"2105302"}))[1][0]["tipo"].endswith("municipio_fora_do_cadastro")
    assert validar_lote(df, contexto(serie_esperada="DESLIGNC"))[1][0]["tipo"].endswith("serie_fora_do_arquivo")
    assert validar_lote(df, contexto(series={}))[1][0]["tipo"].endswith("serie_desconhecida")


@pytest.mark.parametrize("caminho, esperado", [
    ("data/processed/admissoes/ipeadata/ADMISNC/ano=2024.csv", ("ADMISNC", "particao_municipal", 2024)),
    ("data/processed/agregados/ipeadata/DESLIGNC.csv", ("DESLIGNC", "agregados", None)),
    ("data/processed/referencia_nacional/ipeadata/CAGED12_ADMIS.csv", ("CAGED12_ADMIS", "referencia_nacional", None)),
])
def test_escopo_do_arquivo(caminho, esperado):
    assert escopo_do_arquivo(caminho) == esperado


def test_md5_canonico_independe_da_ordem_e_detecta_mudanca():
    df = observacoes([valor("ADMISNC", "2020-01-01", 1, "Municípios", "2111300"), valor("ADMISNC", "2020-01-01", 2, "Brasil", "0")])
    assert md5_linhas(df) == md5_linhas(df.iloc[::-1])
    alterado = df.copy()
    alterado.loc[0, "valor"] = 3
    assert md5_linhas(alterado) != md5_linhas(df)


@pytest.mark.parametrize("entrada, esperado", [("2025-03", date(2025, 3, 1)), ("2025-03-17", date(2025, 3, 1)),
                                               (date(2025, 3, 9), date(2025, 3, 1)), (None, None)])
def test_competencia(entrada, esperado):
    assert competencia(entrada) == esperado


def test_competencia_invalida():
    with pytest.raises(ErroConsulta):
        competencia("março/2025")


def test_ranking_valida_parametros_antes_de_consultar():
    c = ConsultasEmprego(fonte=None)  # type: ignore[arg-type]  # não chega a consultar
    for kwargs in ({"indicador": "x"}, {"ordem": "aleatoria"}, {"limite": 0}):
        with pytest.raises(ErroConsulta):
            c.ranking_municipios(**kwargs)


def test_url_do_banco_escapa_senha_e_separa_banco_de_testes():
    config = ConfigBanco(senha="p@ss:w/rd#", banco="emprego_maranhao", banco_testes="emprego_maranhao_test")
    url = make_url(config.url_principal)
    assert url.password == "p@ss:w/rd#" and url.database == "emprego_maranhao" and url.drivername == "postgresql+psycopg"
    assert make_url(config.url_banco_testes).database == "emprego_maranhao_test"
    assert ConfigBanco(url="postgresql+psycopg://u@h/x").url_principal.endswith("/x")


def test_leitura_em_lotes_equivale_a_leitura_inteira(tmp_path):
    df = observacoes([valor("ADMISNC", f"2020-{m:02d}-01", m, "Municípios", "2111300") for m in range(1, 11)])
    caminho = tmp_path / "x.csv"
    df.to_csv(caminho, index=False)
    lotes = list(esquema.ler_csv_em_lotes(caminho, esquema.OBSERVACAO, 3))
    assert [len(l) for l in lotes] == [3, 3, 3, 1]
    pd.testing.assert_frame_equal(pd.concat(lotes, ignore_index=True), esquema.ler_csv(caminho, esquema.OBSERVACAO))

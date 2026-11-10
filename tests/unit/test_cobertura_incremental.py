from __future__ import annotations

from datetime import date

import pandas as pd

from coleta import cobertura, incremental
from coleta.config import SERIES
from coleta.transformacao import ContextoSerie, EntradaPainel, montar_painel, processar
from tests.conftest import OFICIAIS, metadados, valor

M = "Municípios"
INFO = {
    "admissoes": {"serie_codigo": "ADMISNC", "metodologia": "Novo Caged - sem ajuste", "fonte": "IpeaData"},
    "desligamentos": {"serie_codigo": "DESLIGNC", "metodologia": "Novo Caged - sem ajuste", "fonte": "IpeaData"},
}


def obs(codigo, registros):
    ctx = ContextoSerie(SERIES[codigo], metadados(codigo), "MA", "21", dict(OFICIAIS), "t", "exec", "raw")
    return processar([registros], ctx).observacoes


def municipios():
    return pd.DataFrame({"cod_ibge": list(OFICIAIS), "municipio": list(OFICIAIS.values()), "uf": "MA"})


# --- Cobertura ------------------------------------------------------------------------

def test_matriz_anual_distingue_todas_as_situacoes():
    adm = [valor("ADMISNC", m, 3, M, "2111300") for m in ("2020-11-01", "2020-12-01", "2021-01-01")]
    adm += [valor("ADMISNC", "2020-11-01", 0, M, "2105302")]  # Imperatriz: 1 de 2 meses em 2020, zero
    entrada_adm = EntradaPainel(SERIES["ADMISNC"], obs("ADMISNC", adm), date(2020, 11, 1), date(2021, 1, 1))
    entrada_desl = EntradaPainel(SERIES["DESLIGNC"], obs("ADMISNC", adm).iloc[0:0], None, None, coleta_ok=False)
    painel = montar_painel(entrada_adm, entrada_desl, municipios())

    mensal = cobertura.matriz_mensal(painel, {"admissoes": {date(2020, 12, 1)}})
    anual = cobertura.matriz_anual(mensal, municipios(), range(2019, 2022), INFO)
    a = anual.set_index(["codigo_ibge", "ano", "indicador"])

    assert a.loc[("2111300", 2020, "admissoes"), "status_cobertura"] == "completo"
    assert a.loc[("2111300", 2020, "admissoes"), "meses_esperados"] == 2  # só nov-dez: disponibilidade real
    assert a.loc[("2105302", 2020, "admissoes"), "status_cobertura"] == "incompleto"
    assert a.loc[("2105302", 2020, "admissoes"), "meses_valor_zero"] == 1
    assert a.loc[("2105302", 2020, "admissoes"), "meses_ausentes_lista"] == "2020-12"
    assert a.loc[("2105302", 2020, "admissoes"), "meses_lacuna_sistemica_fonte"] == 1
    assert a.loc[("2103000", 2020, "admissoes"), "status_cobertura"] == "sem_registros"
    assert a.loc[("2111300", 2019, "admissoes"), "status_cobertura"] == "nao_disponibilizado_pela_fonte"
    assert a.loc[("2111300", 2019, "admissoes"), "meses_esperados"] == 0
    assert a.loc[("2111300", 2020, "desligamentos"), "status_cobertura"] == "falha_coleta"
    assert list(anual.columns[:8]) == ["codigo_ibge", "municipio", "ano", "indicador", "fonte", "serie_codigo",
                                       "metodologia", "meses_esperados"]
    assert len(anual) == 3 * 3 * 2


def test_resumo_lista_municipios_sem_dados_e_ausencias():
    adm = [valor("ADMISNC", "2020-01-01", 3, M, "2111300")]
    entrada = EntradaPainel(SERIES["ADMISNC"], obs("ADMISNC", adm), date(2020, 1, 1), date(2020, 1, 1))
    entrada_d = EntradaPainel(SERIES["DESLIGNC"], obs("DESLIGNC", [valor("DESLIGNC", "2020-01-01", 1, M, "2111300")]),
                              date(2020, 1, 1), date(2020, 1, 1))
    painel = montar_painel(entrada, entrada_d, municipios())
    mensal = cobertura.matriz_mensal(painel, {})
    anual = cobertura.matriz_anual(mensal, municipios(), [2020], INFO)
    resumo = cobertura.resumo(mensal, anual, municipios())["por_indicador"]["admissoes"]
    assert resumo["municipios_com_dados"] == 1
    assert resumo["municipios_sem_dados"] == ["2103000", "2105302"]
    assert len(resumo["observacoes_ausentes"]) == 2


# --- Incremental -----------------------------------------------------------------------

def test_comparar_classifica_novas_revisoes_e_ausentes():
    base = obs("ADMISNC", [valor("ADMISNC", m, 10, M, "2111300") for m in ("2020-01-01", "2020-02-01", "2020-03-01")])
    nova = obs("ADMISNC", [
        valor("ADMISNC", "2020-01-01", 11, M, "2111300"),  # revisão antiga (fora da janela)
        valor("ADMISNC", "2020-03-01", 12, M, "2111300"),  # revisão recente (na janela)
        valor("ADMISNC", "2020-04-01", 13, M, "2111300"),  # mês novo
    ])                                                     # 2020-02 sumiu da fonte
    dif = incremental.comparar(base, nova, janela_meses=2)
    assert dif.inicio_janela == date(2020, 3, 1)
    assert dif.contagens() == {"novas": 1, "revisadas_na_janela": 1, "revisadas_fora_janela": 1, "ausentes_na_fonte": 1}

    final, anos = incremental.aplicar(base, nova, dif, aplicar_fora_janela=False)
    valores = dict(zip(final["data_referencia"].dt.strftime("%Y-%m"), final["valor"]))
    assert valores == {"2020-01": 10, "2020-02": 10, "2020-03": 12, "2020-04": 13}
    assert anos == {2020}

    final, _ = incremental.aplicar(base, nova, dif, aplicar_fora_janela=True)
    assert dict(zip(final["data_referencia"].dt.strftime("%Y-%m"), final["valor"]))["2020-01"] == 11

    log = incremental.registro_alteracoes(dif, aplicar_fora_janela=False, remover_ausentes=False)
    assert dict(zip(log["tipo"], log["aplicada"])) == {
        "nova": True, "revisada_na_janela": True, "revisada_fora_janela": False, "ausente_na_fonte": False,
    }


def test_aplicar_sem_diferencas_nao_toca_particoes():
    base = obs("ADMISNC", [valor("ADMISNC", "2020-01-01", 10, M, "2111300")])
    dif = incremental.comparar(base, base.copy(), janela_meses=12)
    assert dif.vazia
    final, anos = incremental.aplicar(base, base.copy(), dif, aplicar_fora_janela=False)
    assert anos == set() and final is base


def test_linhas_inalteradas_mantem_proveniencia_original():
    base = obs("ADMISNC", [valor("ADMISNC", "2020-01-01", 10, M, "2111300")])
    nova = obs("ADMISNC", [valor("ADMISNC", "2020-01-01", 10, M, "2111300"), valor("ADMISNC", "2020-02-01", 5, M, "2111300")])
    nova["execucao_id"] = "exec-nova"
    final, _ = incremental.aplicar(base, nova, incremental.comparar(base, nova, 12), False)
    proveniencia = dict(zip(final["data_referencia"].dt.strftime("%Y-%m"), final["execucao_id"]))
    assert proveniencia == {"2020-01": "exec", "2020-02": "exec-nova"}

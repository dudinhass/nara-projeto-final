from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from coleta.config import SERIES, SerieConfig
from coleta.transformacao import (
    ContextoSerie,
    EntradaPainel,
    converter_data,
    converter_valor,
    detectar_quedas,
    montar_painel,
    processar,
)
from tests.conftest import OFICIAIS, metadados, valor

M = "Municípios"


def contexto(codigo="ADMISNC", periodicidade="Mensal"):
    return ContextoSerie(SERIES[codigo], metadados(codigo, periodicidade=periodicidade), "MA", "21", dict(OFICIAIS),
                         "2026-10-25T12:00:00+00:00", "exec-teste", "data/raw/ipeadata/x.json.gz")


# --- Conversões -------------------------------------------------------------------

def test_converter_data_ignora_fuso_para_nao_deslocar_mes():
    assert converter_data("2020-01-01T00:00:00-03:00") == date(2020, 1, 1)
    assert converter_data("2020-13-01T00:00:00") is None
    assert converter_data(None) is None


@pytest.mark.parametrize(
    "bruto, indicador, esperado",
    [
        (172.0, "admissoes", (172, None)),
        ("15", "admissoes", (15, None)),
        (0.0, "admissoes", (0, None)),
        (None, "admissoes", (None, "valor_nulo")),
        ("abc", "admissoes", (None, "valor_nao_numerico")),
        (float("nan"), "admissoes", (None, "valor_nao_numerico")),
        (True, "admissoes", (None, "valor_nao_numerico")),
        (1.5, "admissoes", (None, "valor_nao_inteiro")),
        (-3.0, "desligamentos", (None, "valor_negativo")),
        (-3.0, "saldo", (-3, None)),  # saldo pode ser negativo
    ],
)
def test_converter_valor(bruto, indicador, esperado):
    assert converter_valor(bruto, indicador) == esperado


# --- Filtragem do Maranhão e validação de códigos -------------------------------------

def test_filtra_maranhao_e_classifica_registros():
    registros = [
        valor("ADMISNC", "2020-01-01", 10, M, "2111300"),      # aceito
        valor("ADMISNC", "2020-01-01", 10, M, "2211001"),      # outra UF -> excluído
        valor("ADMISNC", "2020-01-01", 10, M, "2199999"),      # MA, fora da lista oficial -> rejeitado
        valor("ADMISNC", "2020-01-01", 10, M, "211130"),       # 6 dígitos -> rejeitado
        valor("ADMISNC", "2020-01-01", 10, "Estados", "21"),   # total da UF -> aceito como estado
        valor("ADMISNC", "2020-01-01", 10, "Estados", "22"),   # outra UF -> excluído
        valor("ADMISNC", "2020-01-01", 10, "Brasil", "0"),     # aceito como brasil
        valor("ADMISNC", "2020-01-01", 10, "Regiões", "2"),    # nível não usado -> excluído
        valor("ADMISNC", "2020-01-01", None, M, "2105302"),    # nulo -> rejeitado (não vira zero)
        valor("ADMISNC", "2020-01-15", 3, M, "2103000"),       # dia != 1 numa série mensal
        valor("ADMISNC", "data-ruim", 3, M, "2103000"),
    ]
    r = processar([registros], contexto())
    assert r.estatisticas["excluidos"] == {"outra_uf": 2, "nivel_nao_utilizado": 1}
    assert r.estatisticas["rejeitados"] == {
        "codigo_fora_do_cadastro_ipeadata": 1, "codigo_municipal_malformado": 1, "valor_nulo": 1,
        "data_fora_do_padrao_mensal": 1, "data_invalida": 1,
    }
    obs = r.observacoes.set_index("nivel_territorial")
    assert sorted(r.observacoes["nivel_territorial"]) == ["brasil", "estado", "municipio"]
    assert obs.loc["municipio", "cod_ibge"] == "2111300"
    assert obs.loc["municipio", "territorio_nome"] == "São Luís"  # nome da lista oficial
    assert obs.loc["estado", "cod_ibge"] == "21" and obs.loc["estado", "uf"] == "MA"
    assert obs.loc["brasil", "cod_ibge"] == "" and obs.loc["brasil", "uf"] == ""
    assert set(r.rejeitados["motivo"]) == set(r.estatisticas["rejeitados"])


def test_preserva_origem_e_metodologia():
    r = processar([[valor("ADMISNC", "2020-01-01", 10, M, "2111300")]], contexto())
    linha = r.observacoes.iloc[0]
    assert linha["fonte"] == "IpeaData"
    assert linha["fonte_original"] == "MTE/Caged"
    assert linha["metodologia"] == "Novo Caged - sem ajuste"
    assert linha["serie_codigo"] == "ADMISNC" and linha["indicador"] == "admissoes"
    assert linha["unidade"] == "Pessoa" and linha["periodicidade"] == "Mensal"
    assert linha["nivel_territorial_original"] == "Municípios" and linha["cod_territorio_original"] == "2111300"
    assert linha["arquivo_bruto"] == "data/raw/ipeadata/x.json.gz"
    assert linha["execucao_id"] == "exec-teste"
    assert linha["valor"] == 10 and str(r.observacoes["valor"].dtype) == "Int64"
    assert linha["data_referencia"] == pd.Timestamp("2020-01-01") and linha["mes"] == 1


def test_serie_nacional_vira_brasil_sem_territorio():
    r = processar([[valor("CAGED12_SALDON12", "2020-01-01", -5, "", "")]], contexto("CAGED12_SALDON12"))
    linha = r.observacoes.iloc[0]
    assert linha["nivel_territorial"] == "brasil" and linha["valor"] == -5


# --- Duplicatas -----------------------------------------------------------------------

def test_duplicatas_exatas_removidas_e_conflitantes_rejeitadas():
    registros = [
        valor("ADMISNC", "2020-01-01", 10, M, "2111300"),
        valor("ADMISNC", "2020-01-01", 10, M, "2111300"),  # repetição exata
        valor("ADMISNC", "2020-01-01", 4, M, "2105302"),
        valor("ADMISNC", "2020-01-01", 9, M, "2105302"),   # mesma chave, outro valor
    ]
    r = processar([registros], contexto())
    assert r.estatisticas["duplicatas_exatas_removidas"] == 1
    assert r.estatisticas["chaves_conflitantes"] == 1
    assert r.observacoes["cod_ibge"].tolist() == ["2111300"]
    assert (r.rejeitados["motivo"] == "chave_duplicada_conflitante").sum() == 2


# --- Disponibilidade e lacunas sistêmicas ---------------------------------------------------

def test_disponibilidade_usa_nivel_municipal_do_pais_inteiro():
    registros = [valor("ADMISNC", "2019-12-01", 1, M, "2211001"), valor("ADMISNC", "2020-03-01", 1, M, "2111300")]
    disp = processar([registros], contexto()).estatisticas["disponibilidade"]
    assert (disp["inicio"], disp["fim"], disp["periodos"]) == ("2019-12-01", "2020-03-01", 2)


def test_detectar_quedas_aponta_mes_com_menos_territorios():
    contagem = {date(2023, 12, 1): 5570, date(2024, 1, 1): 5463, date(2024, 2, 1): 5570, date(2024, 3, 1): 5571}
    assert detectar_quedas(contagem) == [date(2024, 1, 1)]
    assert detectar_quedas({date(2020, 1, 1): 10, date(2020, 3, 1): 10}) == [date(2020, 2, 1)]  # mês sem registros
    assert detectar_quedas({}) == []


# --- Painel ---------------------------------------------------------------------------

def _municipios():
    return pd.DataFrame({"cod_ibge": list(OFICIAIS), "municipio": list(OFICIAIS.values()), "uf": "MA"})


def _entrada(codigo, registros, inicio=date(2020, 1, 1), fim=date(2020, 2, 1), ok=True):
    obs = processar([registros], contexto(codigo)).observacoes
    return EntradaPainel(SERIES[codigo], obs, inicio, fim, ok)


def test_painel_distingue_zero_ausente_e_calcula_saldo_so_com_ambos():
    adm = _entrada("ADMISNC", [valor("ADMISNC", "2020-01-01", 10, M, "2111300"), valor("ADMISNC", "2020-02-01", 0, M, "2111300")])
    desl = _entrada("DESLIGNC", [valor("DESLIGNC", "2020-01-01", 4, M, "2111300")])
    painel = montar_painel(adm, desl, _municipios()).set_index(["cod_ibge", "data_referencia"])
    jan, fev = painel.loc[("2111300", pd.Timestamp("2020-01-01"))], painel.loc[("2111300", pd.Timestamp("2020-02-01"))]
    assert (jan["admissoes"], jan["desligamentos"], jan["saldo"]) == (10, 4, 6)
    assert jan["status_admissoes"] == "valor_encontrado"
    assert fev["status_admissoes"] == "zero_encontrado"
    assert fev["status_desligamentos"] == "observacao_ausente"
    assert pd.isna(fev["saldo"])
    assert len(painel) == 3 * 2  # grade completa: 3 municípios × 2 meses


def test_painel_marca_falha_de_coleta_e_periodo_indisponivel():
    adm = _entrada("ADMISNC", [valor("ADMISNC", "2020-01-01", 10, M, "2111300")], fim=date(2020, 2, 1))
    desl = EntradaPainel(SERIES["DESLIGNC"], adm.observacoes.iloc[0:0], None, None, coleta_ok=False)
    painel = montar_painel(adm, desl, _municipios())
    assert set(painel["status_desligamentos"]) == {"falha_coleta"}

    curta = _entrada("DESLIGNC", [valor("DESLIGNC", "2020-01-01", 1, M, "2111300")], fim=date(2020, 1, 1))
    painel = montar_painel(adm, curta, _municipios())
    fev = painel[painel["data_referencia"] == "2020-02-01"]
    assert set(fev["status_desligamentos"]) == {"nao_disponibilizado_pela_fonte"}


def test_painel_recusa_metodologias_diferentes():
    adm = _entrada("ADMISNC", [valor("ADMISNC", "2020-01-01", 1, M, "2111300")])
    outra = EntradaPainel(SerieConfig("X", "desligamentos", "CAGED tradicional", "municipal"),
                          adm.observacoes, date(2020, 1, 1), date(2020, 1, 1))
    with pytest.raises(ValueError, match="metodologias"):
        montar_painel(adm, outra, _municipios())

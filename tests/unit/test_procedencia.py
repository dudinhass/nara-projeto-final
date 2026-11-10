"""Regra do projeto: todos os dados vêm do IpeaData, e a procedência é comprovada."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
import responses

from banco.auditoria import (
    Auditor,
    chave_do_banco,
    chaves_de_observacoes,
    comparar_observacoes,
    datas_de_amostra,
)
from coleta.checkpoint import Checkpoint
from coleta.config import (
    CODIGOS_SERIES_AUTORIZADAS,
    HOSTS_AUTORIZADOS,
    RAIZ_PROJETO,
    SERIES,
    ConfigAPI,
    SerieConfig,
)
from coleta.ipea_client import ErroFonteNaoAutorizada, IpeaClient, verificar_url_autorizada
from coleta.pipeline import Pipeline
from coleta.procedencia import (
    codigo_na_url,
    comparar_metadados,
    host_autorizado,
    url_corresponde_a_serie,
    verificar_metadados,
)
from coleta.transformacao import ContextoSerie, processar
from tests.conftest import BASE, OFICIAIS, M, metadados, valor

ADM = SERIES["ADMISNC"]
URL_ADM = "https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')"


# --- Só o IpeaData: endereços ---------------------------------------------------------------

def test_hosts_autorizados_de_producao_so_tem_o_ipeadata():
    assert HOSTS_AUTORIZADOS == ("www.ipeadata.gov.br",)
    assert ConfigAPI().hosts_autorizados == ("www.ipeadata.gov.br",)


@pytest.mark.parametrize(
    "url",
    [
        "https://servicodados.ibge.gov.br/api/v1/localidades/estados/21/municipios",
        "ftp://ftp.mtps.gov.br/pdet/microdados/",
        "http://www.ipeadata.gov.br/api/odata4/Metadados",                      # sem TLS
        "https://www.ipeadata.gov.br.outro-site.com/api/odata4/Metadados",     # host parecido
        "https://outro-site.com/www.ipeadata.gov.br/api/odata4/Metadados",     # nome no caminho
        "https://usuario:senha@www.ipeadata.gov.br/api/odata4/Metadados",      # credenciais embutidas
    ],
)
def test_enderecos_fora_do_ipeadata_sao_recusados(url):
    with pytest.raises(ErroFonteNaoAutorizada):
        verificar_url_autorizada(url, HOSTS_AUTORIZADOS)
    assert not host_autorizado(url)


def test_cliente_recusa_url_base_de_outro_portal():
    with pytest.raises(ErroFonteNaoAutorizada):
        IpeaClient(ConfigAPI(base_url="https://servicodados.ibge.gov.br/api/"))


@responses.activate
def test_cliente_recusa_link_de_paginacao_para_outro_host(cliente):
    responses.get(f"{BASE}ValoresSerie(SERCODIGO='S')",
                  json={"value": [], "@odata.nextLink": "https://dados.outro-portal.gov.br/pagina2"})
    with pytest.raises(ErroFonteNaoAutorizada):
        cliente.valores_serie("S")
    assert len(responses.calls) == 1  # a segunda requisição nem chegou a ser feita


@responses.activate
def test_cliente_nao_segue_redirecionamento(cliente):
    responses.get(f"{BASE}Metadados('X')", status=302, headers={"Location": "https://outro-portal.gov.br/x"})
    with pytest.raises(ErroFonteNaoAutorizada, match="Redirecionamento recusado"):
        cliente.metadados("X")
    assert len(responses.calls) == 1


def test_nenhuma_rotina_do_projeto_aponta_para_outro_portal():
    """Varre o código-fonte atrás de qualquer endereço que não seja do IpeaData."""
    achados = {}
    for pasta in ("coleta", "banco", "scripts"):
        for arquivo in (RAIZ_PROJETO / pasta).rglob("*.py"):
            for host, proximo in re.findall(r"https?://([A-Za-z0-9._-]+)(.?)", arquivo.read_text(encoding="utf-8")):
                if proximo != "\\" and host not in HOSTS_AUTORIZADOS:  # "\\" = trecho de expressão regular
                    achados.setdefault(host, []).append(arquivo.name)
    assert achados == {}, f"Endereços fora do IpeaData no código: {achados}"


def test_somente_o_ipeadata_e_fonte_autorizada_na_tabela_de_fontes():
    fontes = Pipeline._tabela_fontes().set_index("fonte")
    assert fontes[fontes["autorizada_para_coleta"]].index.tolist() == ["IpeaData"]
    assert fontes.loc["MTE/Caged", "tipo_fonte"] == "origem_estatistica"
    assert "IBGE - API de localidades" not in fontes.index


# --- Série, metadados e URL precisam corresponder ---------------------------------------------

@pytest.mark.parametrize(
    "url, codigo, esperado",
    [
        (URL_ADM, "ADMISNC", True),
        (URL_ADM, "DESLIGNC", False),                                            # série diferente
        (URL_ADM + "?$filter=TERCODIGO%20eq%20'21'", "ADMISNC", True),
        ("https://www.ipeadata.gov.br/api/odata4/Metadados('ADMISNC')", "ADMISNC", False),  # não é a consulta de valores
        ("https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')/x", "ADMISNC", False),
        ("https://servicodados.ibge.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')", "ADMISNC", False),
    ],
)
def test_url_precisa_ser_do_ipeadata_e_da_serie_esperada(url, codigo, esperado):
    assert url_corresponde_a_serie(url, codigo) is esperado


def test_codigo_na_url():
    assert codigo_na_url(URL_ADM) == "ADMISNC"
    assert codigo_na_url("https://www.ipeadata.gov.br/api/odata4/Metadados('ADMISNC')", "metadados") == "ADMISNC"
    assert codigo_na_url("https://x/qualquer") is None


@pytest.mark.parametrize(
    "mudanca, trecho",
    [
        ({"SERCODIGO": "OUTRA"}, "difere do solicitado"),
        ({"SERNUMERICA": False}, "não numérica"),
        ({"BASNOME": "Social"}, "base"),
        ({"PERNOME": "Anual"}, "periodicidade"),
        ({"UNINOME": "R$"}, "unidade"),
    ],
)
def test_metadados_incompativeis_sao_apontados(mudanca, trecho):
    problemas = verificar_metadados(ADM, {**metadados("ADMISNC"), **mudanca})
    assert any(trecho in p for p in problemas)


def test_metadados_ok_e_serie_inexistente():
    assert verificar_metadados(ADM, metadados("ADMISNC")) == []
    assert verificar_metadados(ADM, None) == ["série ADMISNC não existe no IpeaData"]


def test_comparar_metadados_banco_vs_ipeadata():
    armazenado = {"nome": "A", "periodicidade": "Mensal", "unidade": "Pessoa", "base_ipeadata": "Regional"}
    vivo = {"SERNOME": "B", "PERNOME": "Mensal", "UNINOME": "Pessoa", "BASNOME": "Regional"}
    assert comparar_metadados(armazenado, vivo) == {"nome": ("A", "B")}


def test_so_as_series_configuradas_sao_autorizadas():
    assert CODIGOS_SERIES_AUTORIZADAS == set(SERIES) and "ADMIS" not in CODIGOS_SERIES_AUTORIZADAS
    assert all(s.base_ipeadata for s in SERIES.values())


# --- Pipeline recusa séries sem procedência --------------------------------------------------------

def test_serie_inexistente_no_ipeadata_e_rejeitada(criar_pipeline, estado_fonte):
    del estado_fonte["metadados"]["ADMISNC"]
    resumo = criar_pipeline().executar()
    assert resumo["tarefas"]["serie:ADMISNC"]["status"] == "falhou"
    assert "não existe no IpeaData" in resumo["tarefas"]["serie:ADMISNC"]["erro"]
    assert "ADMISNC" not in estado_fonte["downloads"]  # nem chegou a baixar


def test_serie_com_metadados_incompativeis_nao_e_baixada(criar_pipeline, estado_fonte):
    estado_fonte["metadados"]["DESLIGNC"] = metadados("DESLIGNC", periodicidade="Anual")
    resumo = criar_pipeline().executar()
    assert resumo["tarefas"]["serie:DESLIGNC"]["status"] == "falhou"
    assert "Procedência não comprovada" in resumo["tarefas"]["serie:DESLIGNC"]["erro"]
    assert "DESLIGNC" not in estado_fonte["downloads"]


def test_observacao_de_outra_serie_e_rejeitada():
    ctx = ContextoSerie(ADM, metadados("ADMISNC"), "MA", "21", dict(OFICIAIS), "t", "e", "data/raw/ipeadata/x.json.gz")
    r = processar([[valor("ADMISNC", "2020-01-01", 1, M, "2111300"), valor("DESLIGNC", "2020-01-01", 2, M, "2111300")]], ctx)
    assert len(r.observacoes) == 1 and r.estatisticas["rejeitados"] == {"serie_divergente": 1}


def test_serie_nacional_nao_aceita_dados_territoriais():
    nacional = SERIES["CAGED12_ADMISN12"]
    ctx = ContextoSerie(nacional, metadados("CAGED12_ADMISN12"), "MA", "21", dict(OFICIAIS), "t", "e", "x")
    r = processar([[valor("CAGED12_ADMISN12", "2020-01-01", 5, "", ""),
                    valor("CAGED12_ADMISN12", "2020-01-01", 9, "Municípios", "2111300"),
                    valor("CAGED12_ADMISN12", "2020-01-01", 7, "Estados", "21")]], ctx)
    assert r.observacoes["nivel_territorial"].tolist() == ["brasil"]
    assert r.estatisticas["rejeitados"] == {"nivel_inesperado_em_serie_nacional": 2}


def test_cadastro_de_municipios_sai_so_do_ipeadata(criar_pipeline, dirs, estado_fonte):
    criar_pipeline().executar()
    assert estado_fonte["downloads"].count("Territorios") == 1
    resultado = Checkpoint(dirs.checkpoints).tarefa("territorios")["ultima_conclusao"]["resultado"]
    assert resultado["fonte_do_cadastro"] == "IpeaData - entidade Territorios"
    assert not (dirs.dados / "raw" / "ibge").exists()
    assert "ibge" not in (dirs.consolidado / "fontes.csv").read_text(encoding="utf-8").lower()


# --- Comparação com a resposta oficial (funções puras) ------------------------------------------

def _banco(linhas):
    return pd.DataFrame(linhas, columns=["id", "nivel", "cod", "data", "valor"]).assign(
        data=lambda d: pd.to_datetime(d["data"]).dt.date)


def test_comparar_observacoes_separa_iguais_diferentes_e_ausentes():
    banco = _banco([(1, "municipio", "2111300", "2020-01-01", 10), (2, "municipio", "2111300", "2020-02-01", 20),
                    (3, "municipio", "2111300", "2020-03-01", 30), (4, "brasil", "BR", "2020-01-01", 99)])
    fonte = _banco([(0, "municipio", "2111300", "2020-01-01", 10), (0, "municipio", "2111300", "2020-02-01", 21),
                    (0, "municipio", "2111300", "2020-04-01", 40), (0, "brasil", "BR", "2020-01-01", 99)]).drop(columns="id")
    c = comparar_observacoes(banco, fonte)
    assert c.ids_iguais == {1, 4}
    assert [d["id"] for d in c.valor_diferente] == ["2"]
    assert [d["id"] for d in c.somente_banco] == [3] and c.somente_fonte == 1
    assert c.resumo() == {"iguais": 2, "valor_diferente": 1, "somente_no_banco": 1, "somente_na_fonte": 1}


def test_chaves_normalizam_brasil_e_nivel():
    assert chave_do_banco("Brasil", "0") == ("brasil", "BR") and chave_do_banco("", "") == ("brasil", "BR")
    assert chave_do_banco("Municípios", "2111300") == ("municipio", "2111300")
    assert chave_do_banco("Regiões", "2") is None
    ctx = ContextoSerie(ADM, metadados("ADMISNC"), "MA", "21", dict(OFICIAIS), "t", "e", "x")
    obs = processar([[valor("ADMISNC", "2020-01-01", 1, "Brasil", "0")]], ctx).observacoes
    assert chaves_de_observacoes(obs).iloc[0].tolist()[:2] == ["brasil", "BR"]


def test_datas_de_amostra_cobrem_inicio_meio_e_fim():
    from datetime import date

    assert datas_de_amostra(date(2020, 1, 1), date(2026, 8, 1)) == [date(2020, 1, 1), date(2023, 6, 1), date(2026, 8, 1)]
    assert datas_de_amostra(date(2020, 1, 1), date(2020, 1, 1)) == [date(2020, 1, 1)]


def test_classificacao_so_valida_o_que_passou_em_todas_as_verificacoes():
    banco = pd.DataFrame({"id": [1, 2, 3, 4, 5], "snapshot_id": [10, 10, 10, 10, None]})
    snaps = {10: {"ok": True, "incompativel": False}}
    ok_raw, ok_vivo = {1, 2, 3, 5}, {1, 2, 4, 5}
    validos, incompat, motivos = Auditor._classificar(banco, snaps, ok_raw, ok_vivo, True, True)
    assert validos == {1, 2} and incompat == set()
    assert motivos == {"ausente_ou_diferente_na_resposta_oficial_atual": 1, "diverge_do_arquivo_bruto": 1,
                       "sem_arquivo_bruto_de_origem": 1}


def test_classificacao_incompativel_e_serie_nao_comprovada():
    banco = pd.DataFrame({"id": [1, 2], "snapshot_id": [10, 11]})
    snaps = {10: {"ok": False, "incompativel": True}, 11: {"ok": True, "incompativel": False}}
    assert Auditor._classificar(banco, snaps, {1, 2}, {1, 2}, True, True)[:2] == ({2}, {1})
    assert Auditor._classificar(banco, snaps, {1, 2}, {1, 2}, True, False)[:2] == (set(), {1, 2})  # fonte não autorizada
    assert Auditor._classificar(banco, snaps, {1, 2}, {1, 2}, False, True)[0] == set()             # metadados divergem


def test_series_de_teste_existem_na_configuracao():
    assert isinstance(SERIES["ADMISNC"], SerieConfig) and Path(RAIZ_PROJETO).exists()

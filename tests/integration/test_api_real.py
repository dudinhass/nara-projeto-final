"""Testes contra a API real do IpeaData (única fonte do projeto).

Desligados por padrão. Para rodar:  IPEA_TESTES_INTEGRACAO=1 pytest tests/integration
O teste que baixa a série municipal completa (~64 MB) exige também IPEA_TESTES_LENTOS=1.
Se o IpeaData estiver fora do ar, estes testes FALHAM (não passam em silêncio): a verificação não foi feita.
"""

from __future__ import annotations

import os

import pytest

from coleta import territorios
from coleta.config import MUNICIPIOS_TESTE, SERIES, TOTAL_MUNICIPIOS_MA
from coleta.ipea_client import IpeaClient
from coleta.leitor_odata import DocumentoOData
from coleta.procedencia import url_corresponde_a_serie, url_territorios_valida, verificar_metadados

pytestmark = [
    pytest.mark.integracao,
    pytest.mark.skipif(os.getenv("IPEA_TESTES_INTEGRACAO") != "1", reason="defina IPEA_TESTES_INTEGRACAO=1"),
]


@pytest.fixture(scope="module")
def cliente():
    with IpeaClient() as c:
        yield c


def test_conexao(cliente):
    resultado = cliente.testar_conexao()
    assert resultado["ok"] and "Metadados" in resultado["entidades"]


def test_series_candidatas(cliente):
    assert cliente.metadados("ADMISNC")["BASNOME"] == "Regional"
    assert cliente.metadados("DESLIGNC")["BASNOME"] == "Regional"
    assert cliente.metadados("ADMIS") is None
    assert cliente.metadados("DESLIG") is None


@pytest.mark.parametrize("codigo", list(SERIES))
def test_toda_serie_configurada_existe_e_tem_metadados_compativeis(cliente, codigo):
    resposta = cliente.resposta_metadados(codigo)
    assert resposta.url.startswith("https://www.ipeadata.gov.br/api/odata4/Metadados(")
    meta = resposta.valores[0] if resposta.valores else None
    assert verificar_metadados(SERIES[codigo], meta) == []


def test_cadastro_de_municipios_vem_so_do_ipeadata(cliente):
    resposta = cliente.resposta_territorios("21")
    assert url_territorios_valida(resposta.url)
    municipios, problemas = territorios.validar_cadastro(resposta.valores, "21", TOTAL_MUNICIPIOS_MA, "estrita")
    assert len(municipios) == TOTAL_MUNICIPIOS_MA and problemas == []
    assert set(MUNICIPIOS_TESTE) <= set(municipios)
    estado = cliente.resposta_estado("21").valores
    assert estado and estado[0]["TERNOME"] == "Maranhão"  # confere a constante sigla -> código da UF


def test_download_em_fluxo_de_serie_nacional(cliente, tmp_path):
    destino = tmp_path / "CAGED12_ADMISN12.json.gz"
    download = cliente.baixar_para_arquivo(cliente.caminho_valores("CAGED12_ADMISN12"), destino)
    assert url_corresponde_a_serie(download.url, "CAGED12_ADMISN12")
    documento = DocumentoOData(destino)
    assert documento.validar().proxima_pagina is None
    registros = list(documento.registros())
    assert download.bytes == download.content_length
    assert len(registros) >= 80 and min(r["VALDATA"] for r in registros).startswith("2020-01")
    assert {r["SERCODIGO"] for r in registros} == {"CAGED12_ADMISN12"}


@pytest.mark.skipif(os.getenv("IPEA_TESTES_LENTOS") != "1", reason="defina IPEA_TESTES_LENTOS=1 (baixa ~64 MB)")
def test_serie_municipal_completa_tem_os_217_municipios(cliente, tmp_path):
    destino = tmp_path / "ADMISNC.json.gz"
    cliente.baixar_para_arquivo(cliente.caminho_valores("ADMISNC"), destino)
    municipios = {
        r["TERCODIGO"] for r in DocumentoOData(destino).registros()
        if r["NIVNOME"] == "Municípios" and r["TERCODIGO"].startswith("21")
    }
    assert len(municipios) == TOTAL_MUNICIPIOS_MA

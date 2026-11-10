from __future__ import annotations

import gzip
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests
import responses

from coleta.ipea_client import (
    IpeaConnectionError,
    IpeaHTTPError,
    IpeaResponseError,
    LimitadorRequisicoes,
    interpretar_retry_after,
)
from tests.conftest import BASE, valor

META = {"SERCODIGO": "ADMISNC", "SERNOME": "Empregados - admissões", "BASNOME": "Regional"}


# --- Conexão e metadados --------------------------------------------------------

@responses.activate
def test_testar_conexao_ok(cliente):
    responses.get(BASE, json={"value": [{"name": "Metadados"}, {"name": "Territorios"}]})
    resultado = cliente.testar_conexao()
    assert resultado["ok"] is True
    assert resultado["entidades"] == ["Metadados", "Territorios"]


@responses.activate
def test_testar_conexao_falha_sem_excecao(cliente):
    responses.get(BASE, body=requests.ConnectionError("sem rede"))
    resultado = cliente.testar_conexao()
    assert resultado["ok"] is False and "sem rede" in resultado["erro"]


@responses.activate
def test_metadados_existente(cliente):
    responses.get(f"{BASE}Metadados('ADMISNC')", json={"value": [META]})
    assert cliente.metadados("ADMISNC") == META


@responses.activate
def test_metadados_inexistente_retorna_none(cliente):
    # Comportamento real da API: código inexistente -> HTTP 200 com lista vazia.
    responses.get(f"{BASE}Metadados('ADMIS')", json={"value": []})
    assert cliente.metadados("ADMIS") is None


def test_codigo_malicioso_rejeitado(cliente):
    with pytest.raises(ValueError):
        cliente.metadados("X') or ('1'='1")


@responses.activate
def test_valores_em_memoria(cliente):
    responses.get(f"{BASE}ValoresSerie(SERCODIGO='S')", json={"value": [valor("S", "2020-01-01", 1, "Brasil", "0")]})
    assert cliente.valores_serie("S")[0]["VALVALOR"] == 1


# --- Paginação ------------------------------------------------------------------

@responses.activate
def test_paginacao_segue_next_link(cliente):
    proxima = f"{BASE}ValoresSerie(SERCODIGO='S')?$skip=1"
    responses.get(f"{BASE}ValoresSerie(SERCODIGO='S')",
                  json={"value": [valor("S", "2020-01-01", 1, "Brasil", "0")], "@odata.nextLink": proxima})
    responses.get(proxima, json={"value": [valor("S", "2020-02-01", 2, "Brasil", "0")]})
    assert [r["VALVALOR"] for r in cliente.valores_serie("S")] == [1, 2]


@responses.activate
def test_paginacao_em_laco_e_interrompida(cliente):
    url = f"{BASE}ValoresSerie(SERCODIGO='S')"
    responses.get(url, json={"value": [], "@odata.nextLink": url + "?p=2"})
    responses.get(url + "?p=2", json={"value": [], "@odata.nextLink": url + "?p=2"})
    with pytest.raises(IpeaResponseError, match="laço"):
        cliente.valores_serie("S")


# --- Novas tentativas, 429 e 5xx --------------------------------------------------

@responses.activate
def test_retenta_503_com_backoff_exponencial(cliente, esperas):
    url = f"{BASE}Metadados('ADMISNC')"
    responses.get(url, status=503)
    responses.get(url, status=502)
    responses.get(url, json={"value": [META]})
    assert cliente.metadados("ADMISNC") == META
    assert esperas == [1.0, 2.0]


@responses.activate
def test_429_respeita_retry_after_em_segundos(cliente, esperas):
    url = f"{BASE}Metadados('ADMISNC')"
    responses.get(url, status=429, headers={"Retry-After": "7"})
    responses.get(url, json={"value": [META]})
    assert cliente.metadados("ADMISNC") == META
    assert esperas == [7.0]  # maior que o backoff (1 s)


@responses.activate
def test_429_retry_after_limitado_pelo_backoff_maximo(cliente, esperas):
    url = f"{BASE}Metadados('ADMISNC')"
    responses.get(url, status=429, headers={"Retry-After": "3600"})
    responses.get(url, json={"value": [META]})
    cliente.metadados("ADMISNC")
    assert esperas == [60.0]


def test_retry_after_em_data_http():
    agora = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    assert interpretar_retry_after(format_datetime(agora + timedelta(seconds=30), usegmt=True), agora) == 30
    assert interpretar_retry_after("lixo") is None
    assert interpretar_retry_after(None) is None


@responses.activate
def test_esgota_tentativas_e_levanta_http_error(cliente, esperas):
    responses.get(f"{BASE}Metadados('ADMISNC')", status=500)
    with pytest.raises(IpeaHTTPError) as erro:
        cliente.metadados("ADMISNC")
    assert erro.value.status == 500
    assert len(responses.calls) == 3 and len(esperas) == 2


@responses.activate
def test_erro_404_nao_e_retentado(cliente, esperas):
    responses.get(f"{BASE}Valores", status=404, json={"error": {"code": "", "message": "No HTTP resource"}})
    with pytest.raises(IpeaHTTPError, match="No HTTP resource"):
        cliente.listar("Valores")
    assert len(responses.calls) == 1 and esperas == []


@responses.activate
def test_timeout_vira_connection_error_apos_tentativas(cliente):
    responses.get(f"{BASE}Metadados('ADMISNC')", body=requests.Timeout("lento"))
    with pytest.raises(IpeaConnectionError, match="lento"):
        cliente.metadados("ADMISNC")
    assert len(responses.calls) == 3


# --- JSON inválido ----------------------------------------------------------------

@responses.activate
def test_json_invalido(cliente):
    responses.get(f"{BASE}Metadados", body="<html>manutenção</html>", status=200)
    with pytest.raises(IpeaResponseError, match="não é JSON"):
        cliente.catalogo_metadados()


@pytest.mark.parametrize(
    "corpo, mensagem",
    [
        ([1, 2], "esperado objeto"),
        ({"@odata.context": "x"}, "'value' ausente"),
        ({"value": {"a": 1}}, "'value' ausente"),
        ({"error": {"message": "The query specified in the URI is not valid."}}, "not valid"),
    ],
)
@responses.activate
def test_json_fora_do_formato_odata(cliente, corpo, mensagem):
    responses.get(f"{BASE}Metadados", json=corpo)
    with pytest.raises(IpeaResponseError, match=mensagem):
        cliente.catalogo_metadados()


@responses.activate
def test_filtro_odata_em_utf8(cliente):
    responses.get(f"{BASE}Territorios", json={"value": [{"TERCODIGO": "2111300"}]})
    cliente.municipios_uf("21")
    assert responses.calls[0].request.params["$filter"] == "NIVNOME eq 'Municípios' and startswith(TERCODIGO,'21')"
    assert "Munic%C3%ADpios" in responses.calls[0].request.url


# --- Download em fluxo --------------------------------------------------------------

@responses.activate
def test_baixar_para_arquivo_grava_gzip_e_hash(cliente, tmp_path):
    corpo = b'{"value":[{"SERCODIGO":"S","VALVALOR":1}]}'
    # A API real envia Content-Length; o mock só envia se pedirmos.
    responses.get(f"{BASE}ValoresSerie(SERCODIGO='S')", body=corpo, content_type="application/json",
                  headers={"Content-Length": str(len(corpo))})
    destino = tmp_path / "S.json.gz"
    download = cliente.baixar_para_arquivo(cliente.caminho_valores("S"), destino)
    assert gzip.decompress(destino.read_bytes()) == corpo
    assert download.sha256 == hashlib.sha256(corpo).hexdigest()
    assert download.bytes == len(corpo) == download.content_length
    assert not destino.with_name("S.json.gz.part").exists()


@responses.activate
def test_download_truncado_e_retentado(cliente, tmp_path, esperas):
    url = f"{BASE}ValoresSerie(SERCODIGO='S')"
    corpo = b'{"value":[]}'
    responses.get(url, body=corpo, headers={"Content-Length": "999"})  # conexão cai no meio
    responses.get(url, body=corpo)
    destino = tmp_path / "S.json.gz"
    cliente.baixar_para_arquivo(cliente.caminho_valores("S"), destino)
    assert gzip.decompress(destino.read_bytes()) == corpo
    assert len(responses.calls) == 2 and esperas == [1.0]


@responses.activate
def test_download_falho_nao_deixa_arquivo(cliente, tmp_path):
    responses.get(f"{BASE}ValoresSerie(SERCODIGO='S')", status=500)
    destino = tmp_path / "S.json.gz"
    with pytest.raises(IpeaHTTPError):
        cliente.baixar_para_arquivo(cliente.caminho_valores("S"), destino)
    assert list(tmp_path.iterdir()) == []


# --- Limite de taxa -------------------------------------------------------------------

def test_limitador_garante_intervalo_minimo():
    relogio, esperas = [100.0], []

    def esperar(segundos: float) -> None:
        esperas.append(segundos)
        relogio[0] += segundos

    limitador = LimitadorRequisicoes(2.0, relogio=lambda: relogio[0], espera=esperar)
    limitador.aguardar()
    relogio[0] += 0.5
    limitador.aguardar()
    assert esperas == [1.5]

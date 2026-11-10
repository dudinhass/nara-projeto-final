from __future__ import annotations

import gzip
import json

import pytest

from coleta.config import SERIES
from coleta.ipea_client import IpeaResponseError
from coleta.leitor_odata import DocumentoOData
from coleta.transformacao import ContextoSerie, Processador
from tests.conftest import metadados, valor


def gravar(tmp_path, conteudo, nome="doc.json.gz"):
    caminho = tmp_path / nome
    dados = conteudo if isinstance(conteudo, bytes) else json.dumps(conteudo).encode()
    caminho.write_bytes(gzip.compress(dados))
    return caminho


def test_documento_valido_sem_paginacao(tmp_path):
    doc = DocumentoOData(gravar(tmp_path, {"value": [valor("S", "2020-01-01", 1, "Brasil", "0")]}))
    assert doc.validar().proxima_pagina is None
    assert [r["VALVALOR"] for r in doc.registros()] == [1.0]


def test_detecta_proxima_pagina(tmp_path):
    doc = DocumentoOData(gravar(tmp_path, {"value": [], "@odata.nextLink": "https://x/p2"}))
    assert doc.validar().proxima_pagina == "https://x/p2"


def test_lista_vazia_e_valida(tmp_path):
    assert DocumentoOData(gravar(tmp_path, {"value": []})).validar().proxima_pagina is None


@pytest.mark.parametrize(
    "conteudo, mensagem",
    [
        ({"error": {"message": "falhou"}}, "falhou"),
        ({"outra": 1}, "'value' ausente"),
        ([1, 2, 3], "'value' ausente"),
        (b"<html>erro</html>", "JSON inv"),
        (b'{"value": [{"a": 1}, ', "JSON inv"),  # corpo truncado
    ],
)
def test_documentos_invalidos(tmp_path, conteudo, mensagem):
    with pytest.raises(IpeaResponseError, match=mensagem):
        DocumentoOData(gravar(tmp_path, conteudo)).validar()


def test_gzip_corrompido(tmp_path):
    caminho = tmp_path / "x.json.gz"
    caminho.write_bytes(gzip.compress(b'{"value": []}')[:-8])
    with pytest.raises(IpeaResponseError):
        DocumentoOData(caminho).validar()


def test_arquivo_fecha_apos_validacao(tmp_path):
    caminho = gravar(tmp_path, {"value": [valor("S", "2020-01-01", 1, "Brasil", "0")]})
    DocumentoOData(caminho).validar()
    caminho.unlink()  # no Windows falharia se algum handle continuasse aberto


def test_grande_volume_processado_em_lotes(tmp_path):
    """120.001 registros em lotes de 50.000: 3 lotes, nenhum registro perdido."""
    total = 120_001
    registros = [valor("ADMISNC", "2020-01-01", i % 7, "Municípios", "2211001") for i in range(total - 1)]
    registros.append(valor("ADMISNC", "2020-01-01", 3, "Municípios", "2111300"))
    caminho = gravar(tmp_path, {"value": registros})
    documento = DocumentoOData(caminho)
    tamanhos = [len(lote) for lote in documento.lotes(50_000)]
    assert tamanhos == [50_000, 50_000, 20_001]

    ctx = ContextoSerie(SERIES["ADMISNC"], metadados("ADMISNC"), "MA", "21", {"2111300": "São Luís"},
                        "2026-10-25T12:00:00+00:00", "teste", "raw.json.gz")
    processador = Processador(ctx)
    for lote in documento.lotes(50_000):
        processador.processar_lote(lote)
    resultado = processador.resultado()
    assert processador.lotes == 3
    assert resultado.estatisticas["registros_lidos"] == total
    assert resultado.estatisticas["excluidos"] == {"outra_uf": total - 1}
    assert len(resultado.observacoes) == 1


def test_lotes_rejeita_tamanho_invalido(tmp_path):
    with pytest.raises(ValueError):
        list(DocumentoOData(gravar(tmp_path, {"value": []})).lotes(0))

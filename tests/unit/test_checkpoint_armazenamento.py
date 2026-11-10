from __future__ import annotations

import pandas as pd
import pytest

from coleta import esquema
from coleta.armazenamento import (
    escrever_bytes_atomico,
    escrever_particoes,
    ler_particoes,
    limpar_incompletos,
    sha256_arquivo,
)
from coleta.checkpoint import Checkpoint, ErroCheckpoint
from coleta.config import SERIES
from coleta.transformacao import ContextoSerie, processar
from tests.conftest import OFICIAIS, metadados, valor


# --- Checkpoint ------------------------------------------------------------------------

def test_execucao_nova_e_retomada(tmp_path):
    cp = Checkpoint(tmp_path)
    assert cp.iniciar_execucao("full", ["a", "b"]) is False
    execucao = cp.execucao_id
    cp.concluir("a", {"ok": 1}, referencia={"serie_atualizada_em": "x"})

    retomado = Checkpoint(tmp_path)  # relê do disco, como numa nova execução do script
    assert retomado.iniciar_execucao("full", ["a", "b"]) is True
    assert retomado.execucao_id == execucao
    assert not retomado.precisa_executar("a") and retomado.precisa_executar("b")


def test_finalizar_so_encerra_quando_tudo_concluiu(tmp_path):
    cp = Checkpoint(tmp_path)
    cp.iniciar_execucao("full", ["a", "b"])
    cp.concluir("a", {})
    cp.falhar("b", "erro de rede")
    assert cp.finalizar_execucao({}) == "incompleta"
    assert cp.execucao is not None
    cp.concluir("b", {})
    assert cp.finalizar_execucao({}) == "concluida"
    assert cp.execucao is None
    assert [e["status"] for e in cp.historico()] == ["incompleta", "concluida"]


def test_modo_diferente_exige_reinicio(tmp_path):
    cp = Checkpoint(tmp_path)
    cp.iniciar_execucao("full", ["a"])
    with pytest.raises(ErroCheckpoint):
        cp.iniciar_execucao("incremental", ["a"])
    assert cp.iniciar_execucao("incremental", ["a"], reiniciar=True) is False
    assert cp.historico()[-1]["status"] == "descartada"


def test_nova_execucao_preserva_ultima_conclusao(tmp_path):
    cp = Checkpoint(tmp_path)
    cp.iniciar_execucao("full", ["a"])
    cp.concluir("a", {"linhas": 10}, referencia={"serie_atualizada_em": "v1"})
    cp.finalizar_execucao({})
    cp.iniciar_execucao("incremental", ["a"])
    assert cp.tarefa("a")["status"] == "pendente"
    assert cp.tarefa("a")["ultima_conclusao"]["serie_atualizada_em"] == "v1"
    cp.concluir("a", {"situacao": "sem_alteracoes_na_fonte"})  # sem nova referência
    assert cp.tarefa("a")["ultima_conclusao"]["serie_atualizada_em"] == "v1"


def test_estado_gravado_sem_temporarios(tmp_path):
    cp = Checkpoint(tmp_path)
    cp.iniciar_execucao("full", ["a"])
    assert (tmp_path / "estado.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


# --- Armazenamento ---------------------------------------------------------------------

def test_escrita_atomica_substitui_sem_sobras(tmp_path):
    destino = tmp_path / "x" / "a.txt"
    escrever_bytes_atomico(destino, b"um")
    escrever_bytes_atomico(destino, b"dois")
    assert destino.read_bytes() == b"dois"
    assert [p.name for p in destino.parent.iterdir()] == ["a.txt"]


def test_limpar_incompletos(tmp_path):
    (tmp_path / "a.csv.tmp").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.json.gz.part").write_text("x")
    (tmp_path / "ok.csv").write_text("x")
    removidos = limpar_incompletos([tmp_path, tmp_path / "nao_existe"])
    assert len(removidos) == 2 and (tmp_path / "ok.csv").exists()


def _observacoes(registros):
    ctx = ContextoSerie(SERIES["ADMISNC"], metadados("ADMISNC"), "MA", "21", dict(OFICIAIS), "t", "e", "raw")
    return processar([registros], ctx).observacoes


def test_particoes_por_ano_ida_e_volta_preservam_tipos(tmp_path):
    obs = _observacoes([
        valor("ADMISNC", "2020-12-01", 1, "Municípios", "2111300"),
        valor("ADMISNC", "2021-01-01", 0, "Municípios", "2111300"),
        valor("ADMISNC", "2021-01-01", 9, "Brasil", "0"),
    ])
    gravados = escrever_particoes(obs, tmp_path, esquema.OBSERVACAO)
    assert sorted(g["caminho"].name for g in gravados) == ["ano=2020.csv", "ano=2021.csv"]
    assert all(g["sha256"] == sha256_arquivo(g["caminho"]) for g in gravados)
    relido = ler_particoes(tmp_path, esquema.OBSERVACAO)
    pd.testing.assert_frame_equal(
        relido.sort_values(list(esquema.CHAVE_OBSERVACAO)).reset_index(drop=True),
        obs.sort_values(list(esquema.CHAVE_OBSERVACAO)).reset_index(drop=True),
    )
    assert relido.loc[relido["nivel_territorial"] == "brasil", "cod_ibge"].iloc[0] == ""  # vazio, não NaN
    assert str(relido["valor"].dtype) == "Int64" and str(relido["cod_ibge"].dtype) == "string"


def test_particoes_obsoletas_removidas_so_quando_pedido(tmp_path):
    obs = _observacoes([valor("ADMISNC", "2020-01-01", 1, "Municípios", "2111300"),
                        valor("ADMISNC", "2021-01-01", 1, "Municípios", "2111300")])
    escrever_particoes(obs, tmp_path, esquema.OBSERVACAO)
    so_2021 = obs[obs["ano"] == 2021]
    escrever_particoes(so_2021, tmp_path, esquema.OBSERVACAO, anos={2021})
    assert (tmp_path / "ano=2020.csv").exists()
    escrever_particoes(so_2021, tmp_path, esquema.OBSERVACAO, remover_obsoletas=True)
    assert not (tmp_path / "ano=2020.csv").exists()


def test_conformar_exige_todas_as_colunas():
    with pytest.raises(ValueError, match="Colunas ausentes"):
        esquema.conformar(pd.DataFrame({"fonte": ["x"]}), esquema.OBSERVACAO)


def test_substituir_tolera_bloqueio_momentaneo(tmp_path, monkeypatch):
    """Simula o OneDrive/antivírus segurando o arquivo nas duas primeiras tentativas."""
    import os

    from coleta import armazenamento

    origem, destino = tmp_path / "a.tmp", tmp_path / "a"
    origem.write_text("novo")
    original, chamadas, esperas = os.replace, {"n": 0}, []

    def replace_bloqueado(a, b):
        chamadas["n"] += 1
        if chamadas["n"] <= 2:
            raise PermissionError("[WinError 5] Acesso negado")
        original(a, b)

    monkeypatch.setattr(armazenamento.os, "replace", replace_bloqueado)
    armazenamento.substituir(origem, destino, espera=esperas.append)
    assert destino.read_text() == "novo" and len(esperas) == 2


def test_substituir_desiste_apos_limite(tmp_path, monkeypatch):
    from coleta import armazenamento

    monkeypatch.setattr(armazenamento.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("bloqueado")))
    with pytest.raises(PermissionError):
        armazenamento.substituir(tmp_path / "a", tmp_path / "b", tentativas=3, espera=lambda s: None)

"""Checkpoint da coleta: o que já foi feito, o que falhou e o que retomar.

``data/checkpoints/estado.json`` guarda, por tarefa (ex.: ``serie:ADMISNC``):

* ``status``: pendente | em_andamento | concluida | falhou
* ``etapa``: última etapa persistida (``baixada`` | ``persistida``)
* ``download``: arquivos brutos da execução atual (reaproveitados na retomada)
* ``ultima_conclusao``: referência da última carga bem-sucedida, usada pelo
  modo incremental e mantida entre execuções.

Uma execução só é encerrada quando todas as tarefas concluem; se alguma
falhar ou o processo for interrompido, ela continua "em andamento" e a
próxima chamada do mesmo modo retoma apenas o que falta.
``data/checkpoints/execucoes.jsonl`` registra cada tentativa (só cresce).
Todas as gravações do estado são atômicas.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coleta.armazenamento import anexar_jsonl, ler_json, ler_jsonl, salvar_json

logger = logging.getLogger(__name__)

VERSAO = 1
PENDENTE, EM_ANDAMENTO, CONCLUIDA, FALHOU = "pendente", "em_andamento", "concluida", "falhou"


class ErroCheckpoint(RuntimeError):
    """Estado incompatível com a execução pedida."""


def agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Checkpoint:
    def __init__(self, diretorio: Path) -> None:
        self.caminho_estado = diretorio / "estado.json"
        self.caminho_execucoes = diretorio / "execucoes.jsonl"
        self.estado: dict[str, Any] = ler_json(
            self.caminho_estado, {"versao": VERSAO, "execucao_em_andamento": None, "tarefas": {}}
        )

    # --- Persistência --------------------------------------------------------

    def _salvar(self) -> None:
        salvar_json(self.estado, self.caminho_estado)

    @property
    def execucao(self) -> dict[str, Any] | None:
        return self.estado.get("execucao_em_andamento")

    @property
    def execucao_id(self) -> str:
        if not self.execucao:
            raise ErroCheckpoint("Nenhuma execução em andamento")
        return self.execucao["id"]

    # --- Ciclo da execução ---------------------------------------------------

    def iniciar_execucao(self, modo: str, tarefas: list[str], reiniciar: bool = False) -> bool:
        """Inicia ou retoma uma execução. Devolve ``True`` se for retomada."""
        atual = self.execucao
        if atual and not reiniciar:
            if atual["modo"] != modo:
                raise ErroCheckpoint(
                    f"A execução {atual['id']} (modo {atual['modo']}) foi interrompida. "
                    f"Rode o modo {atual['modo']} para retomá-la ou use --reiniciar para descartá-la."
                )
            novas = [nome for nome in tarefas if nome not in atual["tarefas"]]
            for nome in novas:
                self._reiniciar_tarefa(nome, atual["id"])
            atual["tarefas"].extend(novas)
            atual["retomadas"] = atual.get("retomadas", 0) + 1
            self._salvar()
            logger.info(
                "Retomando a execução %s", atual["id"],
                extra={"evento": "execucao_retomada", "execucao_id": atual["id"]},
            )
            return True

        if atual:
            anexar_jsonl(self.caminho_execucoes, {**atual, "status": "descartada", "registrado_em": agora_utc()})
            logger.warning("Execução %s descartada (--reiniciar)", atual["id"], extra={"evento": "execucao_descartada"})

        execucao_id = f"{modo}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        self.estado["execucao_em_andamento"] = {
            "id": execucao_id, "modo": modo, "iniciada_em": agora_utc(), "tarefas": list(tarefas), "retomadas": 0,
        }
        for nome in tarefas:
            self._reiniciar_tarefa(nome, execucao_id)
        self._salvar()
        logger.info("Execução %s iniciada", execucao_id, extra={"evento": "execucao_iniciada", "execucao_id": execucao_id})
        return False

    def _reiniciar_tarefa(self, nome: str, execucao_id: str) -> None:
        anterior = self.estado["tarefas"].get(nome, {})
        self.estado["tarefas"][nome] = {
            "status": PENDENTE,
            "execucao_id": execucao_id,
            "etapa": None,
            "download": None,
            "erro": None,
            "falhas": 0,
            "atualizado_em": agora_utc(),
            "ultima_conclusao": anterior.get("ultima_conclusao"),
        }

    def finalizar_execucao(self, resumo: dict[str, Any]) -> str:
        """Registra a tentativa; encerra a execução só se tudo concluiu."""
        atual = self.execucao
        if not atual:
            raise ErroCheckpoint("Nenhuma execução em andamento")
        pendentes = [n for n in atual["tarefas"] if self.tarefa(n)["status"] != CONCLUIDA]
        status = "concluida" if not pendentes else "incompleta"
        anexar_jsonl(
            self.caminho_execucoes,
            {**deepcopy(atual), "status": status, "pendentes": pendentes, "finalizada_em": agora_utc(), "resumo": resumo},
        )
        if status == "concluida":
            self.estado["execucao_em_andamento"] = None
        self._salvar()
        return status

    def registrar_interrupcao(self, erro: str) -> None:
        """Registra no histórico uma tentativa interrompida por exceção.

        A execução continua em andamento (retomável). Uma queda abrupta do
        processo não chega aqui; ela aparece como ``retomadas`` na tentativa seguinte.
        """
        if self.execucao:
            anexar_jsonl(
                self.caminho_execucoes,
                {**deepcopy(self.execucao), "status": "interrompida", "erro": erro, "registrado_em": agora_utc()},
            )

    # --- Tarefas -------------------------------------------------------------

    def tarefa(self, nome: str) -> dict[str, Any]:
        return self.estado["tarefas"].setdefault(nome, {"status": PENDENTE, "ultima_conclusao": None})

    def precisa_executar(self, nome: str) -> bool:
        info = self.tarefa(nome)
        return not (info["status"] == CONCLUIDA and info.get("execucao_id") == self.execucao_id)

    def atualizar(self, nome: str, **campos: Any) -> None:
        self.tarefa(nome).update(campos, atualizado_em=agora_utc())
        self._salvar()

    def registrar_download(self, nome: str, download: dict[str, Any]) -> None:
        self.atualizar(nome, status=EM_ANDAMENTO, etapa="baixada", download=download)

    def concluir(self, nome: str, resultado: dict[str, Any], referencia: dict[str, Any] | None = None) -> None:
        """Marca como concluída. Chamar só depois de gravar e verificar os arquivos."""
        info = self.tarefa(nome)
        conclusao = {
            "execucao_id": self.execucao_id,
            "modo": self.execucao["modo"],
            "concluida_em": agora_utc(),
            "resultado": resultado,
        }
        if referencia is not None:
            conclusao.update(referencia)
        elif info.get("ultima_conclusao"):
            # Sem nova referência (ex.: fonte sem alterações): preserva a anterior.
            conclusao.update({k: v for k, v in info["ultima_conclusao"].items() if k not in conclusao})
        self.atualizar(nome, status=CONCLUIDA, etapa="persistida", erro=None, ultima_conclusao=conclusao)
        logger.info("Tarefa %s concluída", nome, extra={"evento": "tarefa_concluida", "tarefa": nome})

    def falhar(self, nome: str, erro: str) -> None:
        info = self.tarefa(nome)
        self.atualizar(nome, status=FALHOU, erro=erro, falhas=info.get("falhas", 0) + 1)
        logger.error("Tarefa %s falhou: %s", nome, erro, extra={"evento": "tarefa_falhou", "tarefa": nome})

    def historico(self) -> list[dict[str, Any]]:
        return ler_jsonl(self.caminho_execucoes)

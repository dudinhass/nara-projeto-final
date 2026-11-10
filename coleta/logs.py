"""Logs: legíveis no console e estruturados (JSON por linha) em arquivo."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from coleta.config import DIRETORIOS, NIVEL_LOG

_CAMPOS_PADRAO = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class FormatadorJSON(logging.Formatter):
    """Uma linha JSON por evento, incluindo os campos passados em ``extra``."""

    def format(self, registro: logging.LogRecord) -> str:
        evento = {
            "ts": datetime.fromtimestamp(registro.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": registro.levelname,
            "logger": registro.name,
            "mensagem": registro.getMessage(),
        }
        evento.update({k: v for k, v in registro.__dict__.items() if k not in _CAMPOS_PADRAO})
        if registro.exc_info:
            evento["excecao"] = self.formatException(registro.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logs(nivel: str = NIVEL_LOG) -> None:
    """Console (texto) + ``logs/coleta.log`` (texto) + ``logs/coleta.jsonl`` (JSON)."""
    DIRETORIOS.logs.mkdir(parents=True, exist_ok=True)
    texto = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(texto)
    arquivo_texto = logging.FileHandler(DIRETORIOS.logs / "coleta.log", encoding="utf-8")
    arquivo_texto.setFormatter(texto)
    arquivo_json = logging.FileHandler(DIRETORIOS.logs / "coleta.jsonl", encoding="utf-8")
    arquivo_json.setFormatter(FormatadorJSON())

    raiz = logging.getLogger()
    for handler in raiz.handlers:
        handler.close()
    raiz.handlers.clear()
    raiz.setLevel(nivel.upper())
    for handler in (console, arquivo_texto, arquivo_json):
        raiz.addHandler(handler)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

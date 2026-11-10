"""Engine, fábrica de sessões e controle transacional."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from coleta.config import ConfigBanco, carregar_config_banco

logger = logging.getLogger(__name__)


class ErroConexaoBanco(RuntimeError):
    """O PostgreSQL não respondeu ou recusou a conexão."""


def mascarar_url(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def criar_engine(url: str | None = None, config: ConfigBanco | None = None, **opcoes: Any) -> Engine:
    """Engine com ``pool_pre_ping`` (descarta conexões mortas) e timeout de conexão."""
    config = config or carregar_config_banco()
    return create_engine(
        url or config.url_principal,
        pool_pre_ping=True,
        connect_args={"connect_timeout": config.timeout_conexao, "application_name": "emprego-maranhao"},
        **opcoes,
    )


def verificar_conexao(
    engine: Engine, tentativas: int = 5, espera_s: float = 2.0, espera: Callable[[float], None] = time.sleep
) -> dict[str, str]:
    """Testa a conexão com novas tentativas (útil enquanto o servidor sobe)."""
    ultimo: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            with engine.connect() as conexao:
                linha = conexao.execute(
                    text("SELECT version(), current_database(), current_user, current_setting('TimeZone')")
                ).one()
            return {"versao": linha[0], "banco": linha[1], "usuario": linha[2], "timezone": linha[3]}
        except OperationalError as exc:
            ultimo = exc
            if tentativa < tentativas:
                logger.warning("PostgreSQL indisponível (tentativa %d/%d); aguardando %.0fs",
                               tentativa, tentativas, espera_s, extra={"evento": "banco_indisponivel"})
                espera(espera_s)
    raise ErroConexaoBanco(
        f"Não foi possível conectar a {mascarar_url(str(engine.url))}: {ultimo.orig if hasattr(ultimo, 'orig') else ultimo}. "
        "Verifique se o servidor está rodando (python -m scripts.postgres_local status ou docker compose ps) "
        "e as variáveis POSTGRES_* do .env."
    )


def criar_fabrica_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transacao(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão em uma transação: commit ao sair, rollback em qualquer exceção."""
    with fabrica.begin() as sessao:
        yield sessao

"""Fixtures do PostgreSQL de testes.

Segurança: só roda contra um banco cujo nome termina em ``_test`` e é diferente
do banco principal. O esquema é criado pelas migrações Alembic (não por
``create_all``) e as tabelas são esvaziadas antes de cada teste.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from banco.verificacao import ALEMBIC_INI, TABELAS
from coleta.config import carregar_config_banco


def configuracao_alembic(conexao) -> Config:  # noqa: ANN001
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = conexao
    return config


@pytest.fixture(scope="session")
def engine_testes() -> Engine:
    config = carregar_config_banco()
    url_testes, url_principal = make_url(config.url_banco_testes), make_url(config.url_principal)
    if not (url_testes.database or "").endswith("_test") or url_testes.database == url_principal.database:
        pytest.fail(f"Banco de testes inseguro: {url_testes.database!r} (precisa terminar em _test e não ser o principal)")
    # lock_timeout: um lock esquecido vira erro explícito em vez de travar a suíte.
    engine = create_engine(url_testes, connect_args={"connect_timeout": 5, "options": "-c lock_timeout=30000"})
    try:
        with engine.connect() as con:
            con.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL de testes indisponível ({url_testes.render_as_string()}): {exc.orig}")
    with engine.begin() as con:
        cfg = configuracao_alembic(con)
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def banco(engine_testes: Engine) -> Engine:
    with engine_testes.begin() as con:
        con.execute(text(f"TRUNCATE {', '.join(TABELAS)} RESTART IDENTITY CASCADE"))
    return engine_testes

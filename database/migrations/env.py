"""Ambiente do Alembic.

Ordem de precedência da conexão:
1. conexão passada pelo código (``config.attributes["connection"]``, usada nos testes);
2. ``-x url=...`` na linha de comando;
3. configuração do projeto (.env: DATABASE_URL ou POSTGRES_*).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import pool

from banco.conexao import criar_engine
from banco.modelos import Base

config = context.config
target_metadata = Base.metadata


def _incluir(objeto, nome, tipo, refletido, comparado):  # noqa: ANN001
    # Views são criadas por SQL na migração e não fazem parte dos metadados ORM.
    return not (tipo == "table" and refletido and nome.startswith("vw_"))


def _configurar(conexao) -> None:  # noqa: ANN001
    context.configure(
        connection=conexao,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_incluir,
        transaction_per_migration=True,
    )


def executar_offline() -> None:
    url = context.get_x_argument(as_dictionary=True).get("url") or str(criar_engine().url)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def executar_online() -> None:
    conexao = config.attributes.get("connection")
    if conexao is not None:
        _configurar(conexao)
        with context.begin_transaction():
            context.run_migrations()
        return
    url = context.get_x_argument(as_dictionary=True).get("url")
    engine = criar_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conexao:
        _configurar(conexao)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    executar_offline()
else:
    executar_online()

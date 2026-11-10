"""Funções comuns aos testes de integração com o PostgreSQL de testes."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from banco.auditoria import Auditor
from banco.importacao import Importador
from coleta.armazenamento import ler_json, salvar_json, sha256_arquivo
from tests.conftest import SERIES_TESTE, FakeCliente


def auditar(banco, dirs, estado_fonte, series=None):
    """Auditoria de procedência com a fonte simulada (o 'IpeaData' do teste)."""
    codigos = series or [s.codigo for s in SERIES_TESTE]
    return Auditor(banco, dirs, FakeCliente(estado_fonte), "21", "MA", 4, codigos).executar()


def importar(banco, dirs, tipo="FULL", **kwargs):
    return Importador(banco, dirs, tipo, tamanho_lote=4, total_municipios=None, **kwargs).executar()


def contar(banco, sql: str, **parametros) -> int:
    with banco.connect() as con:
        return con.execute(text(sql), parametros).scalar_one()


# Sempre com "with": uma conexão esquecida aberta segura locks e trava o TRUNCATE da próxima fixture.
def uma_linha(banco, sql: str) -> dict:
    with banco.connect() as con:
        return dict(con.execute(text(sql)).mappings().one())


def todas_as_linhas(banco, sql: str) -> list[tuple]:
    with banco.connect() as con:
        return [tuple(l) for l in con.execute(text(sql))]


def reescrever(dirs, caminho_relativo: str, transformar) -> None:
    """Altera um arquivo processado e atualiza o manifesto, como faria uma nova coleta."""
    caminho = dirs.raiz / caminho_relativo
    df = pd.read_csv(caminho, dtype=str, keep_default_na=False)
    transformar(df).to_csv(caminho, index=False, lineterminator="\n")
    manifesto = ler_json(dirs.processed / "manifesto.json")
    manifesto["arquivos"][caminho_relativo]["sha256"] = sha256_arquivo(caminho)
    salvar_json(manifesto, dirs.processed / "manifesto.json")


PARTICAO_ADM = "data/processed/admissoes/ipeadata/ADMISNC/ano=2020.csv"

"""Gerencia um PostgreSQL local sem Docker (binários portáteis oficiais).

Alternativa ao ``compose.yaml`` para máquinas onde o Docker não roda (ex.:
Windows sem WSL2/Plataforma de Máquina Virtual). Usa os mesmos parâmetros do
.env (POSTGRES_*). Binários e dados ficam fora do repositório, em
%LOCALAPPDATA%\\emprego-maranhao, evitando que o OneDrive sincronize e
bloqueie arquivos do banco.

Uso (na raiz do projeto):
    python -m scripts.postgres_local iniciar   # cria o cluster na 1ª vez, sobe e cria os bancos
    python -m scripts.postgres_local status
    python -m scripts.postgres_local parar
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from coleta.config import carregar_config_banco

PASTA_PADRAO = Path(os.getenv("LOCALAPPDATA", Path.home())) / "emprego-maranhao"
BIN = Path(os.getenv("PG_BIN_DIR") or PASTA_PADRAO / "pg17" / "pgsql" / "bin")
DADOS = Path(os.getenv("PG_DATA_DIR") or PASTA_PADRAO / "pgdata")
LOG = DADOS.parent / "postgres.log"


def _executar(*args: str, verificar: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=verificar)


def _executavel(nome: str) -> str:
    caminho = BIN / f"{nome}.exe" if os.name == "nt" else BIN / nome
    if not caminho.exists():
        raise SystemExit(f"[FALHA] {caminho} não encontrado. Defina PG_BIN_DIR com a pasta bin do PostgreSQL.")
    return str(caminho)


def rodando() -> bool:
    return _executar(_executavel("pg_ctl"), "-D", str(DADOS), "status", verificar=False).returncode == 0


def inicializar_cluster() -> None:
    config = carregar_config_banco()
    if not config.senha:
        raise SystemExit("[FALHA] POSTGRES_PASSWORD não definido no .env")
    DADOS.parent.mkdir(parents=True, exist_ok=True)
    arquivo_senha = DADOS.parent / f".pw-{secrets.token_hex(4)}"
    arquivo_senha.write_text(config.senha, encoding="utf-8")
    try:
        _executar(
            _executavel("initdb"), "-D", str(DADOS), "-U", config.usuario, f"--pwfile={arquivo_senha}",
            "--auth=scram-sha-256", "--encoding=UTF8", "--no-locale",
        )
    finally:
        arquivo_senha.unlink(missing_ok=True)
    with open(DADOS / "postgresql.conf", "a", encoding="utf-8") as conf:
        conf.write(
            "\n# emprego-maranhao\n"
            f"port = {config.porta}\n"
            "listen_addresses = 'localhost'\n"
            "timezone = 'UTC'\n"
            "log_timezone = 'UTC'\n"
        )
    print(f"[OK] Cluster criado em {DADOS} (superusuário: {config.usuario})")


def criar_bancos() -> None:
    config = carregar_config_banco()
    with psycopg.connect(
        host=config.host, port=config.porta, user=config.usuario, password=config.senha,
        dbname="postgres", autocommit=True, connect_timeout=config.timeout_conexao,
    ) as conexao:
        for banco in (config.banco, config.banco_testes):
            existe = conexao.execute("SELECT 1 FROM pg_database WHERE datname = %s", (banco,)).fetchone()
            if existe:
                print(f"[OK] Banco {banco} já existe")
            else:
                conexao.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(banco), sql.Identifier(config.usuario)))
                print(f"[OK] Banco {banco} criado")


def iniciar() -> int:
    if not (DADOS / "PG_VERSION").exists():
        inicializar_cluster()
    if rodando():
        print("[OK] PostgreSQL já está rodando")
    else:
        # Sem capturar a saída: no Windows o processo do servidor herdaria os pipes e o
        # subprocess esperaria o servidor terminar. A saída vai para o arquivo de log (-l).
        codigo = subprocess.call(
            [_executavel("pg_ctl"), "-D", str(DADOS), "-l", str(LOG), "-w", "-t", "60", "start"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if codigo != 0:
            print(f"[FALHA] pg_ctl start terminou com código {codigo}. Veja o log: {LOG}")
            return 1
        print(f"[OK] PostgreSQL iniciado (log: {LOG})")
    criar_bancos()
    return 0


def parar() -> int:
    if not rodando():
        print("[OK] PostgreSQL já estava parado")
        return 0
    resultado = _executar(_executavel("pg_ctl"), "-D", str(DADOS), "-m", "fast", "-w", "stop", verificar=False)
    print("[OK] PostgreSQL parado" if resultado.returncode == 0 else f"[FALHA] {resultado.stderr}")
    return resultado.returncode


def status() -> int:
    config = carregar_config_banco()
    print(f"Binários: {BIN}\nDados:    {DADOS}\nPorta:    {config.porta}")
    pronto = _executar(_executavel("pg_isready"), "-h", config.host, "-p", str(config.porta), verificar=False)
    print(f"Situação: {'rodando' if rodando() else 'parado'} | pg_isready: {pronto.stdout.strip()}")
    return 0 if pronto.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("acao", choices=["iniciar", "parar", "status"])
    acao = parser.parse_args(argv).acao
    return {"iniciar": iniciar, "parar": parar, "status": status}[acao]()


if __name__ == "__main__":
    sys.exit(main())

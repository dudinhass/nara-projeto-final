"""Gera os relatórios em docs/ a partir dos artefatos reais.

Etapa 1: cobertura_historica.md, relatorio_validacao_etapa1.md, modelo_dados.md.
Etapa 2: relatorio_etapa2.md (se houver verificação do banco em data/reports).

Uso (na raiz do projeto):
    python -m scripts.gerar_relatorio
"""

from __future__ import annotations

import argparse
import sys

from banco import auditoria_relatorio, relatorio as relatorio_banco
from banco.conexao import ErroConexaoBanco, criar_engine, verificar_conexao
from coleta.config import DIRETORIOS
from coleta.relatorios import GeradorRelatorios


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    for nome, caminho in GeradorRelatorios(DIRETORIOS).gerar().items():
        print(f"[OK] {nome}: {caminho}")
    print(f"[OK] relatorio_etapa2: {relatorio_banco.gerar(DIRETORIOS)}")
    engine = criar_engine()
    try:
        verificar_conexao(engine, tentativas=1)
    except ErroConexaoBanco as exc:
        print(f"[AVISO] auditoria_origem_ipeadata não gerada: PostgreSQL indisponível ({exc})")
        return 1
    print(f"[OK] auditoria_origem_ipeadata: {auditoria_relatorio.gerar(DIRETORIOS, engine)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

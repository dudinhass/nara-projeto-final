"""Modo FULL: coleta histórica completa de todas as séries configuradas.

Baixa o snapshot completo de cada série no IpeaData, mantém os 217
municípios do Maranhão (validados contra o cadastro do próprio IpeaData) e grava a
base em data/processed/. Se for interrompida, rodar o mesmo comando retoma
do checkpoint.

Uso (na raiz do projeto):
    python -m scripts.coletar_historico
    python -m scripts.coletar_historico --series ADMISNC,DESLIGNC
    python -m scripts.coletar_historico --reiniciar
"""

from __future__ import annotations

import sys

from scripts._execucao import argumentos, executar


def main(argv: list[str] | None = None) -> int:
    args = argumentos(__doc__.splitlines()[0], incremental=False).parse_args(argv)
    return executar("full", args)


if __name__ == "__main__":
    sys.exit(main())

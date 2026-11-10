"""Modo INCREMENTAL: atualiza a base com novos meses e revisões recentes.

Para cada série, compara SERATUALIZACAO com a última carga; se mudou, baixa
o snapshot e aplica observações novas e revisões dentro da janela
(INCREMENTAL_JANELA_MESES). Revisões mais antigas e observações que sumiram
da fonte são apenas registradas em data/reports/alteracoes/. Séries sem base
local recebem carga completa. Rodar duas vezes seguidas não altera nada.

Uso (na raiz do projeto):
    python -m scripts.atualizar_dados
    python -m scripts.atualizar_dados --forcar --janela-meses 24
"""

from __future__ import annotations

import sys

from scripts._execucao import argumentos, executar


def main(argv: list[str] | None = None) -> int:
    args = argumentos(__doc__.splitlines()[0], incremental=True).parse_args(argv)
    return executar("incremental", args)


if __name__ == "__main__":
    sys.exit(main())

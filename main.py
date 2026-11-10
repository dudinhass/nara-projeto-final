"""Ponto de entrada: conexão -> [investigação] -> coleta -> validação -> [banco] -> relatórios.

Uso (na raiz do projeto, com o ambiente virtual ativo):
    python main.py                               # coleta no modo de COLETA_MODO (padrão: full)
    python main.py --modo incremental --importar # atualiza a coleta e leva as novidades ao PostgreSQL
    python main.py --investigar                  # inclui a varredura do catálogo
"""

from __future__ import annotations

import argparse
import sys

from coleta.config import MODOS, carregar_config_coleta
from scripts import (
    atualizar_dados,
    auditar_procedencia,
    coletar_historico,
    gerar_relatorio,
    importar_postgresql,
    investigar_ipea,
    reconciliar_dados,
    testar_requisicao,
    validar_dados,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta IpeaData / Novo Caged / Maranhão e carga no PostgreSQL")
    parser.add_argument("--modo", choices=MODOS, help="sobrescreve COLETA_MODO")
    parser.add_argument("--investigar", action="store_true", help="refaz a varredura do catálogo (lenta)")
    parser.add_argument("--importar", action="store_true",
                        help="importa no PostgreSQL (mesmo tipo da coleta), audita a procedência no IpeaData e reconcilia")
    args = parser.parse_args()
    modo = args.modo or carregar_config_coleta().modo

    etapas = [("Conexão", testar_requisicao.main)]
    if args.investigar:
        etapas.append(("Investigação", investigar_ipea.main))
    coleta = coletar_historico.main if modo == "full" else atualizar_dados.main
    etapas += [(f"Coleta ({modo})", coleta), ("Validação", validar_dados.main)]
    if args.importar:
        etapas += [
            (f"Importação PostgreSQL ({modo})", lambda argv: importar_postgresql.main(["--tipo", modo, *argv])),
            ("Auditoria de procedência (IpeaData)", auditar_procedencia.main),
            ("Reconciliação", reconciliar_dados.main),
        ]
    etapas.append(("Relatórios", gerar_relatorio.main))

    for nome, executar in etapas:
        print(f"\n######## {nome} ########")
        codigo = executar([])
        if codigo != 0:
            print(f"\nEtapa '{nome}' terminou com código {codigo}; execução interrompida.")
            return codigo
    return 0


if __name__ == "__main__":
    sys.exit(main())

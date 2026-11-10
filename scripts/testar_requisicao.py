"""Testa a conectividade com o IpeaData e a leitura de metadados de uma série.

Uso (na raiz do projeto):
    python -m scripts.testar_requisicao [--serie ADMISNC]
"""

from __future__ import annotations

import argparse
import sys

from coleta.config import SERIES_MUNICIPAIS
from coleta.investigacao import resumir_metadados
from coleta.ipea_client import IpeaAPIError, IpeaClient
from coleta.logs import configurar_logs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serie", default=SERIES_MUNICIPAIS[0].codigo, help="código da série a consultar")
    args = parser.parse_args(argv)
    configurar_logs()

    with IpeaClient() as cliente:
        conexao = cliente.testar_conexao()
        if not conexao["ok"]:
            print(f"[FALHA] API inacessível: {conexao['erro']}")
            return 1
        print(f"[OK] Conectado a {conexao['url']} (HTTP {conexao['status']}, {conexao['latencia_s']}s)")
        print(f"     Entidades expostas: {', '.join(conexao['entidades'])}")

        try:
            meta = cliente.metadados(args.serie)
        except IpeaAPIError as exc:
            print(f"[FALHA] Erro ao consultar metadados de {args.serie}: {exc}")
            return 1

    if meta is None:
        print(f"[AVISO] A série {args.serie} não existe no IpeaData.")
        return 2
    print(f"[OK] Metadados de {args.serie}:")
    for chave, valor in resumir_metadados(meta).items():
        print(f"     {chave:<20} {valor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

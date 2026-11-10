"""Investiga séries de admissões/desligamentos no IpeaData e salva um relatório JSON.

Uso (na raiz do projeto):
    python -m scripts.investigar_ipea
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from coleta.armazenamento import salvar_json
from coleta.config import DIRETORIOS, SERIES_CANDIDATAS, carregar_config_coleta
from coleta.investigacao import investigar
from coleta.ipea_client import IpeaAPIError, IpeaClient
from coleta.logs import configurar_logs

ARQUIVO_RELATORIO = DIRETORIOS.reports / "investigacao_series.json"


def _imprimir(relatorio: dict[str, Any]) -> None:
    print("\n=== Séries candidatas ===")
    for item in relatorio["candidatas"]:
        if not item["existe"]:
            print(f"  {item['codigo']:<10} NÃO EXISTE no IpeaData")
            continue
        print(
            f"  {item['codigo']:<10} {item['nome']} | base {item['base']} | {item['fonte_sigla']} "
            f"| {item['periodicidade']} | unidade: {item['unidade']}"
        )

    print(f"\n=== Séries relacionadas ({len(relatorio['series_relacionadas'])} de "
          f"{relatorio['catalogo_total_series']} no catálogo) ===")
    for item in relatorio["series_relacionadas"]:
        perfil = item.get("perfil")
        if not perfil:
            print(f"  {item['codigo']:<22} sem perfil ({item.get('erro', 'sem valores')})")
            continue
        niveis = "; ".join(
            f"{nivel}: {p['territorios']} terr., {p['data_inicio']}..{p['data_fim']}"
            for nivel, p in perfil["niveis"].items()
        ) or "sem registros"
        print(f"  {item['codigo']:<22} [{item['situacao']}] {item['nome']}")
        print(f"  {'':<22} {item['periodicidade']} | {perfil['total_registros']} registros | {niveis}")
        print(f"  {'':<22} adequada para análise municipal: {'SIM' if perfil['adequada_para_analise_municipal'] else 'não'}")
        if perfil["tem_dados_municipais"]:
            print(f"  {'':<22} municípios da UF com registros: {perfil['municipios_uf_com_registros']} "
                  f"| teste: {perfil['municipios_teste_presentes']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    configurar_logs()
    try:
        with IpeaClient() as cliente:
            relatorio = investigar(cliente, SERIES_CANDIDATAS, carregar_config_coleta().codigo_uf)
    except IpeaAPIError as exc:
        print(f"[FALHA] Investigação interrompida: {exc}")
        return 1
    _imprimir(relatorio)
    salvar_json(relatorio, ARQUIVO_RELATORIO)
    print(f"\nRelatório salvo em {ARQUIVO_RELATORIO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Valida a base persistida (integridade, territórios, duplicatas, consistência).

Grava data/reports/validacao.json. Sai com código 1 se houver problema crítico.

Uso (na raiz do projeto):
    python -m scripts.validar_dados
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from coleta.armazenamento import salvar_json
from coleta.checkpoint import Checkpoint
from coleta.config import DIRETORIOS, carregar_config_coleta
from coleta.logs import configurar_logs
from coleta.validacao import validar_base

ARQUIVO = DIRETORIOS.reports / "validacao.json"


def _imprimir(r: dict[str, Any]) -> None:
    print(f"\n=== Validação: {r['situacao'].upper()} ===")
    for problema in r["problemas_criticos"]:
        print(f"  [CRÍTICO] {problema}")
    integ = r["integridade_arquivos"]
    print(f"  Arquivos verificados (SHA-256): {integ['arquivos_verificados']} | ausentes: {len(integ['ausentes'])} "
          f"| alterados: {len(integ['sha256_divergente'])}")
    print(f"  Municípios: {r['municipios']['total']} (presentes no IpeaData: {r['municipios']['presentes_no_ipeadata']})")
    print("\n  Série                 Observ.  Período                  Duplic.  Nulos  Brutos OK")
    for codigo, info in r["series"].items():
        campos = info["campos"]
        brutos = info["brutos"]
        ok = "sim" if brutos.get("verificado") and not brutos.get("divergentes") else "não verificado"
        print(f"  {codigo:<21} {campos['observacoes']:>7}  {str(campos['periodo'][0])}..{str(campos['periodo'][1])}  "
              f"{info['duplicados']['linhas_duplicadas']:>7}  {campos['valores_nulos']:>5}  {ok}")
    print(f"\n  Painel: {r['painel']['linhas']}/{r['painel']['linhas_esperadas']} linhas | "
          f"admissões {r['painel']['situacao_admissoes']} | desligamentos {r['painel']['situacao_desligamentos']}")
    print("\n  Consistência (meses divergentes / comparados; maior |dif|; dif. média %):")
    for nome, grupo in r["consistencia"].items():
        if not isinstance(grupo, dict):
            continue
        for sub, comp in grupo.items():
            if isinstance(comp, dict) and "meses_comparados" in comp:
                print(f"    {nome}.{sub}: {comp['meses_divergentes']}/{comp['meses_comparados']}; "
                      f"{comp['maior_diferenca_absoluta']}; {comp['diferenca_media_percentual']}")
    sobre = r["consistencia"].get("caged_tradicional_vs_novo_caged")
    if sobre:
        print(f"    CAGED tradicional {sobre['tradicional']} x Novo Caged {sobre['novo_caged']}: "
              f"{sobre['meses_sobrepostos']} meses sobrepostos; faltantes no tradicional: {sobre['meses_faltantes_tradicional']}")
    print(f"\n  Taxas percentuais calculáveis: {r['indicadores']['taxas_percentuais']}")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    configurar_logs()
    if not (DIRETORIOS.consolidado / "painel_municipal_mensal.csv").exists():
        print("[FALHA] Base não encontrada. Execute antes: python -m scripts.coletar_historico")
        return 1
    estado = Checkpoint(DIRETORIOS.checkpoints).estado
    relatorio = validar_base(DIRETORIOS, estado, carregar_config_coleta().codigo_uf)
    salvar_json(relatorio, ARQUIVO)
    _imprimir(relatorio)
    print(f"\nRelatório salvo em {ARQUIVO}")
    return 0 if relatorio["situacao"] == "aprovada" else 1


if __name__ == "__main__":
    sys.exit(main())

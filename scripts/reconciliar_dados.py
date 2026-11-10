"""Reconcilia os arquivos processados da coleta com o conteúdo do PostgreSQL.

Grava data/reports/reconciliacao_postgresql.json. Sai com código 1 se houver divergência.

Uso (na raiz do projeto):
    python -m scripts.reconciliar_dados
"""

from __future__ import annotations

import argparse
import sys

from banco.conexao import ErroConexaoBanco, criar_engine, verificar_conexao
from banco.reconciliacao import reconciliar
from coleta.armazenamento import salvar_json
from coleta.config import DIRETORIOS, carregar_config_coleta
from coleta.logs import configurar_logs

ARQUIVO = DIRETORIOS.reports / "reconciliacao_postgresql.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="URL SQLAlchemy alternativa (padrão: banco principal)")
    args = parser.parse_args(argv)
    configurar_logs()
    engine = criar_engine(args.url)
    try:
        verificar_conexao(engine, tentativas=2)
    except ErroConexaoBanco as exc:
        print(f"[FALHA] {exc}")
        return 1
    r = reconciliar(engine, DIRETORIOS, carregar_config_coleta().uf_sigla)
    salvar_json(r, ARQUIVO)
    t, m = r["totais"], r["municipios"]
    print(f"=== Reconciliação: {r['situacao'].upper()} ===")
    print(f"  Linhas: origem {t['linhas_origem']} | banco {t['linhas_banco']}")
    print(f"  Soma dos valores: origem {t['soma_origem']} | banco {t['soma_banco']}")
    print(f"  Grupos série×ano: {t['grupos_serie_ano']} (divergentes: {t['grupos_divergentes']}) | "
          f"chaves duplicadas no banco: {t['chaves_duplicadas_no_banco']}")
    print(f"  Municípios: origem {m['cadastro_origem']} | banco {m['cadastro_banco']} | "
          f"só origem {m['somente_origem']} | só banco {m['somente_banco']}")
    print("\n  Série                 Linhas orig.  Linhas banco  Período")
    for s in r["por_serie"]:
        print(f"  {s['serie']:<21} {s['linhas_origem']:>12}  {s['linhas_banco']:>12}  {s['inicio']}..{s['fim']}")
    for codigo, c in r["contagem_por_municipio"].items():
        print(f"  {codigo}: {c['municipios_com_observacoes_banco']} municípios com observações; "
              f"observações por município → {c['distribuicao_observacoes_por_municipio']}")
    for d in r["divergencias"]:
        print(f"  [DIVERGÊNCIA] {d['serie']}/{d['ano']}: só origem {d['somente_na_origem']}, só banco "
              f"{d['somente_no_banco']}, valores diferentes {d['valores_diferentes']}")
    print(f"\nRelatório: {ARQUIVO}")
    return 0 if r["situacao"] == "conciliado" else 1


if __name__ == "__main__":
    sys.exit(main())

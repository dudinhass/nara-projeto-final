"""Verifica o PostgreSQL: migração, tabelas, restrições, integridade e desempenho.

Grava data/reports/verificacao_banco.json (inclui os planos EXPLAIN ANALYZE).

Uso (na raiz do projeto):
    python -m scripts.verificar_banco
"""

from __future__ import annotations

import argparse
import sys

from banco.conexao import ErroConexaoBanco, criar_engine, mascarar_url
from banco.verificacao import verificar
from coleta.armazenamento import salvar_json
from coleta.config import DIRETORIOS, carregar_config_coleta
from coleta.logs import configurar_logs

ARQUIVO = DIRETORIOS.reports / "verificacao_banco.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="URL SQLAlchemy alternativa (padrão: banco principal)")
    args = parser.parse_args(argv)
    configurar_logs()
    engine = criar_engine(args.url)
    config = carregar_config_coleta()
    try:
        r = verificar(engine, config.uf_sigla, config.codigo_uf)
    except ErroConexaoBanco as exc:
        print(f"[FALHA] {exc}")
        return 1
    salvar_json(r, ARQUIVO)

    print(f"Banco: {mascarar_url(str(engine.url))}\n  {r['conexao']['versao'].split(',')[0]} | timezone {r['conexao']['timezone']}")
    m = r["migracao"]
    print(f"  Migração: {m['revisao_atual']} (head {m['revisao_head']}) — {'atualizada' if m['atualizada'] else 'DESATUALIZADA'}")
    print("  Tabelas:", ", ".join(f"{t}={n}" for t, n in r["tabelas"].items()))
    print(f"  Restrições: {r['restricoes']} | índices: {len(r['indices'])} | views: {r['views']}")
    i = r["integridade"]
    print(f"  Integridade: chaves duplicadas={i['chaves_naturais_duplicadas']} | municípios={i['municipios_cadastrados']} | "
          f"sem observação por série={i['municipios_sem_observacao_por_serie']} | séries sem dados={i['series_sem_observacao']}")
    print(f"  Inconsistências registradas: {r['inconsistencias_por_tipo'] or 'nenhuma'} | revisões: {r['revisoes_registradas']}")
    pr = r["procedencia"]
    print(f"  Procedência: registros {pr['registros']} | visíveis nas consultas: {pr['visiveis_nas_consultas']} | "
          f"fontes autorizadas: {pr['fontes_autorizadas']} | sem snapshot: {pr['registros_sem_snapshot']}")
    for d in r.get("desempenho", []):
        print(f"  EXPLAIN {d['consulta']}: {d['tempo_execucao_ms']} ms | índices: {d['indices_usados'] or 'nenhum'}")
    print(f"\nRelatório: {ARQUIVO}")
    ok = m["atualizada"] and i["chaves_naturais_duplicadas"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

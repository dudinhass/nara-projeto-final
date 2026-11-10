"""Consultas analíticas no PostgreSQL pela linha de comando.

Uso (na raiz do projeto):
    python -m scripts.consultar cobertura
    python -m scripts.consultar ranking --indicador saldo --inicio 2025-01 --fim 2025-12 --limite 10
    python -m scripts.consultar municipio 2111300                 # histórico completo (anual + mensal)
    python -m scripts.consultar mensal 2111300 --inicio 2024-01 --fim 2024-12
    python -m scripts.consultar uf --inicio 2025-01 --fim 2025-12  # totais do Maranhão
    python -m scripts.consultar periodo --inicio 2025-01 --fim 2025-12
    python -m scripts.consultar comparar 2111300 2105302 2103000 --inicio 2025-01 --fim 2025-12
    python -m scripts.consultar periodos --a 2024-01:2024-12 --b 2025-01:2025-12 [--municipio 2111300]
    python -m scripts.consultar nacional --indicador admissoes     # CAGED tradicional → Novo Caged
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import pandas as pd

from banco.conexao import ErroConexaoBanco, criar_engine, verificar_conexao
from banco.consultas import METODOLOGIA_PADRAO, ConsultasEmprego, ErroConsulta
from coleta.config import carregar_config_coleta


def _tabela(linhas: list[dict[str, Any]]) -> None:
    if not linhas:
        print("(sem resultados)")
        return
    print(pd.DataFrame(linhas).to_string(index=False))


def _periodo(texto: str) -> tuple[str, str]:
    inicio, _, fim = texto.partition(":")
    return inicio, fim or inicio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(__doc__.splitlines()[2:]))
    parser.add_argument("--metodologia", default=METODOLOGIA_PADRAO)
    parser.add_argument("--url", help="URL SQLAlchemy alternativa")
    sub = parser.add_subparsers(dest="consulta", required=True)
    sub.add_parser("cobertura")
    sub.add_parser("ultima")
    for nome in ("ranking", "uf", "periodo", "comparar", "mensal"):
        p = sub.add_parser(nome)
        p.add_argument("--inicio")
        p.add_argument("--fim")
        if nome == "ranking":
            p.add_argument("--indicador", default="saldo", choices=["admissoes", "desligamentos", "saldo"])
            p.add_argument("--limite", type=int, default=10)
            p.add_argument("--ordem", default="desc", choices=["desc", "asc"])
        if nome == "comparar":
            p.add_argument("codigos", nargs="+")
        if nome == "mensal":
            p.add_argument("codigo", nargs="?", help="código IBGE (omita para a UF)")
    p = sub.add_parser("municipio")
    p.add_argument("codigo")
    p = sub.add_parser("periodos")
    p.add_argument("--a", required=True, help="AAAA-MM:AAAA-MM")
    p.add_argument("--b", required=True, help="AAAA-MM:AAAA-MM")
    p.add_argument("--municipio")
    p = sub.add_parser("nacional")
    p.add_argument("--indicador", default="admissoes", choices=["admissoes", "desligamentos", "saldo"])
    args = parser.parse_args(argv)

    engine = criar_engine(args.url)
    try:
        verificar_conexao(engine, tentativas=1)
    except ErroConexaoBanco as exc:
        print(f"[FALHA] {exc}")
        return 1
    config = carregar_config_coleta()
    c = ConsultasEmprego(engine, config.uf_sigla, config.codigo_uf)
    m = args.metodologia
    try:
        if args.consulta == "cobertura":
            _tabela(c.cobertura_series())
        elif args.consulta == "ultima":
            print(f"Última competência ({m}, municipal): {c.ultima_competencia(m):%Y-%m}")
        elif args.consulta == "ranking":
            _tabela(c.ranking_municipios(args.indicador, args.inicio, args.fim, args.limite, args.ordem, m))
        elif args.consulta == "uf":
            totais = c.totais_uf(args.inicio, args.fim, m)
            _tabela(totais.pop("mensal"))
            print({k: v for k, v in totais.items()})
        elif args.consulta == "periodo":
            print(c.indicadores_periodo(args.inicio, args.fim, m))
        elif args.consulta == "comparar":
            _tabela(c.comparar_municipios(args.codigos, inicio=args.inicio, fim=args.fim, metodologia=m))
        elif args.consulta == "mensal":
            _tabela(c.evolucao_mensal(args.codigo, args.inicio, args.fim, m))
        elif args.consulta == "municipio":
            h = c.historico_municipio(args.codigo, m)
            print(h["municipio"])
            _tabela(h["anual"])
            print(f"({len(h['mensal'])} meses na série mensal; use 'mensal {args.codigo}' para ver)")
        elif args.consulta == "periodos":
            r = c.comparar_periodos(_periodo(args.a), _periodo(args.b), args.municipio, m)
            print(pd.DataFrame([r["periodo_a"], r["periodo_b"]], index=["A", "B"]).to_string())
            print(f"Diferença (B − A): {r['diferenca']} | períodos completos e comparáveis: {r['periodos_comparaveis']}")
        elif args.consulta == "nacional":
            linhas = c.serie_nacional(args.indicador)
            for quebra in (l for l in linhas if l["inicio_da_metodologia"]):
                print(f"Início de '{quebra['metodologia']}' em {quebra['data_referencia']:%Y-%m} (quebra metodológica)")
            print(f"{len(linhas)} meses; últimos 3:")
            _tabela(linhas[-3:])
    except ErroConsulta as exc:
        print(f"[ERRO] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

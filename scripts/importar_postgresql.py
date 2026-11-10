"""Importa os dados processados da coleta para o PostgreSQL (FULL ou INCREMENTAL).

Pré-requisitos: banco migrado (alembic -c database/alembic.ini upgrade head) e
coleta concluída e validada (scripts.coletar_historico / scripts.validar_dados).

Uso (na raiz do projeto):
    python -m scripts.importar_postgresql --tipo full
    python -m scripts.importar_postgresql --tipo incremental
"""

from __future__ import annotations

import argparse
import sys

from banco.conexao import ErroConexaoBanco, criar_engine, mascarar_url, verificar_conexao
from banco.importacao import ErroImportacao, Importador
from coleta.config import DIRETORIOS, carregar_config_banco, carregar_config_coleta
from coleta.logs import configurar_logs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tipo", choices=["full", "incremental"], default="incremental")
    parser.add_argument("--tamanho-lote", type=int, help="linhas por lote de leitura (IMPORTACAO_TAMANHO_LOTE)")
    parser.add_argument("--url", help="URL SQLAlchemy alternativa (padrão: banco principal do .env)")
    args = parser.parse_args(argv)
    configurar_logs()

    config_banco, config_coleta = carregar_config_banco(), carregar_config_coleta()
    engine = criar_engine(args.url, config_banco)
    try:
        verificar_conexao(engine)
    except ErroConexaoBanco as exc:
        print(f"[FALHA] {exc}")
        return 1
    print(f"Banco: {mascarar_url(str(engine.url))}")

    importador = Importador(
        engine, DIRETORIOS, args.tipo, args.tamanho_lote or config_banco.tamanho_lote,
        config_coleta.codigo_uf, config_coleta.total_municipios_esperado,
    )
    try:
        resumo = importador.executar()
    except ErroImportacao as exc:
        print(f"[FALHA] {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n[INTERROMPIDO] Arquivos já confirmados permanecem. Rode a importação incremental para continuar.")
        return 130

    t = resumo.totais
    print(f"\n=== Importação {resumo.importacao_id} ({resumo.tipo}) — {resumo.status} — {resumo.duracao_s}s ===")
    print(f"  Arquivos: {t['arquivos_processados']} processados, {t['arquivos_ignorados']} ignorados "
          f"({t['arquivos_com_problema']} por problema de integridade)")
    print(f"  Lidos: {t['lidos']} | válidos: {t['validos']} | inseridos: {t['inseridos']} | atualizados: "
          f"{t['atualizados']} | inalterados: {t['inalterados']} | rejeitados: {t['rejeitados']} | "
          f"ausentes na origem: {t['ausentes_na_origem']} | revisões registradas: {t['revisoes']}")
    print(f"  Registros no banco após a carga: {sum(resumo.registros_no_banco.values())}")
    for codigo, total in resumo.registros_no_banco.items():
        print(f"    {codigo:<22} {total}")
    print("  [!] Registros novos ou revisados ficam 'não validados' até a auditoria: "
          "python -m scripts.auditar_procedencia (só dados validados aparecem nas consultas).")
    for aviso in resumo.avisos:
        print(f"  [AVISO] {aviso}")
    return 0 if resumo.status == "concluida" else 1


if __name__ == "__main__":
    sys.exit(main())

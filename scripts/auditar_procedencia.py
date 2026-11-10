"""Audita a procedência dos dados do PostgreSQL contra as respostas oficiais do IpeaData.

Baixa de novo cada série, compara observação a observação com o banco e com o arquivo bruto
preservado, e grava o status de procedência (validado_ipeadata / nao_validado / incompativel).
Só os registros validados aparecem nas consultas analíticas (views vw_*_validados). Nada é apagado.

Uso (na raiz do projeto):
    python -m scripts.auditar_procedencia
    python -m scripts.auditar_procedencia --series ADMISNC,DESLIGNC
"""

from __future__ import annotations

import argparse
import sys

from banco.auditoria import Auditor
from banco.conexao import ErroConexaoBanco, criar_engine, mascarar_url, verificar_conexao
from coleta.config import CODIGOS_SERIES_AUTORIZADAS, DIRETORIOS, carregar_config_api, carregar_config_banco, carregar_config_coleta
from coleta.ipea_client import IpeaAPIError, IpeaClient
from coleta.logs import configurar_logs


def imprimir(r: dict) -> None:
    print(f"\n=== Auditoria {r['auditoria_id']}: {r['status'].upper()} ({r['duracao_s']} s) ===")
    t = r["territorios"]
    print(f"  Municípios: {t.get('validados', 0)} validados / {t.get('municipios_no_banco', '—')} no banco "
          f"(IpeaData: {t.get('municipios_no_ipeadata', '—')}) — {t['situacao']}")
    for p in t.get("problemas", []):
        print(f"    [!] {p}")
    print("\n  Série                  Registros  Validados  Não valid.  Incompat.  Situação")
    for codigo, s in r["series"].items():
        print(f"  {codigo:<22} {s.get('registros', 0):>9}  {s.get('validados', 0):>9}  {s.get('nao_validados', 0):>10}  "
              f"{s.get('incompativeis', 0):>9}  {s['situacao']}")
        for problema in s.get("problemas", []):
            print(f"      [!] {problema}")
        if s.get("motivos_nao_validado"):
            print(f"      motivos: {s['motivos_nao_validado']}")
    amostras = [a for s in r["series"].values() for a in s.get("amostras", [])]
    diverg = [a for a in amostras if a["situacao"] == "DIVERGENTE"]
    print(f"\n  Amostras diretas da resposta oficial: {len(amostras)} comparadas, {len(diverg)} divergentes")
    print(f"  Requisições registradas como evidência: {len(r['evidencias_http'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", help="códigos separados por vírgula (padrão: todas)")
    parser.add_argument("--url", help="URL SQLAlchemy alternativa do banco")
    args = parser.parse_args(argv)
    configurar_logs()
    series = [c.strip() for c in args.series.split(",")] if args.series else None
    if series and (invalidas := [c for c in series if c not in CODIGOS_SERIES_AUTORIZADAS]):
        print(f"[FALHA] Séries não configuradas: {invalidas}")
        return 2
    engine = criar_engine(args.url)
    try:
        verificar_conexao(engine, tentativas=2)
    except ErroConexaoBanco as exc:
        print(f"[FALHA] {exc}")
        return 1
    print(f"Banco: {mascarar_url(str(engine.url))}")
    config = carregar_config_coleta()
    try:
        with IpeaClient(carregar_config_api()) as cliente:
            resultado = Auditor(engine, DIRETORIOS, cliente, config.codigo_uf, config.uf_sigla,
                                carregar_config_banco().tamanho_lote * 10, series).executar()
    except IpeaAPIError as exc:
        print(f"[FALHA] IpeaData indisponível: {exc}")
        return 1
    imprimir(resultado)
    print(f"\nEvidências: {DIRETORIOS.reports / 'auditoria_procedencia.json'}")
    return 0 if resultado["status"] == "concluida" else 1


if __name__ == "__main__":
    sys.exit(main())

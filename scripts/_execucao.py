"""Partes comuns de ``coletar_historico`` (FULL) e ``atualizar_dados`` (INCREMENTAL)."""

from __future__ import annotations

import argparse
from typing import Any

from coleta.checkpoint import ErroCheckpoint
from coleta.config import DIRETORIOS, SERIES, carregar_config_api, carregar_config_coleta
from coleta.logs import configurar_logs
from coleta.pipeline import Pipeline, fabrica_cliente_padrao
from coleta.territorios import ErroTerritorial

CODIGO_INTERROMPIDO = 130


def argumentos(descricao: str, incremental: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=descricao)
    parser.add_argument("--series", help="códigos separados por vírgula (padrão: todas as séries configuradas)")
    parser.add_argument("--reiniciar", action="store_true", help="descarta uma execução interrompida e começa outra")
    parser.add_argument("--concorrencia", type=int, help="downloads simultâneos (sobrescreve COLETA_MAX_CONCORRENCIA)")
    if incremental:
        parser.add_argument("--forcar", action="store_true", help="baixa mesmo se SERATUALIZACAO não mudou")
        parser.add_argument("--janela-meses", type=int, help="janela de revisão (sobrescreve INCREMENTAL_JANELA_MESES)")
    return parser


def executar(modo: str, args: argparse.Namespace) -> int:
    configurar_logs()
    config = carregar_config_coleta(
        modo=modo,
        max_concorrencia=args.concorrencia,
        janela_incremental_meses=getattr(args, "janela_meses", None),
    )
    series = None
    if args.series:
        codigos = [c.strip() for c in args.series.split(",") if c.strip()]
        desconhecidos = [c for c in codigos if c not in SERIES]
        if desconhecidos:
            print(f"[FALHA] Séries não configuradas: {desconhecidos}. Disponíveis: {list(SERIES)}")
            return 2
        series = [SERIES[c] for c in codigos]

    pipeline = Pipeline(
        config,
        DIRETORIOS,
        fabrica_cliente_padrao(carregar_config_api()),
        series=series,
        reiniciar=args.reiniciar,
        forcar=getattr(args, "forcar", False),
    )
    comando = "python -m scripts." + ("coletar_historico" if modo == "full" else "atualizar_dados")
    try:
        resumo = pipeline.executar()
    except KeyboardInterrupt:
        print(f"\n[INTERROMPIDO] Checkpoint preservado. Para retomar: {comando}")
        return CODIGO_INTERROMPIDO
    except ErroCheckpoint as exc:
        print(f"[FALHA] {exc}")
        return 2
    except ErroTerritorial as exc:
        print(f"[FALHA] Validação territorial reprovou a coleta: {exc}")
        print(f"        Execução preservada como incompleta. Corrija e rode novamente: {comando}")
        return 1

    imprimir_resumo(resumo)
    if resumo["status"] != "concluida":
        print(f"\n[INCOMPLETA] Há tarefas pendentes ou com falha. Para retomar só o que falta: {comando}")
        return 1
    return 0


def imprimir_resumo(resumo: dict[str, Any]) -> None:
    print(f"\n=== Execução {resumo['execucao_id']} ({resumo['modo']}) — {resumo['status']} ===")
    if resumo["retomada"]:
        print("  (execução retomada a partir do checkpoint)")
    if resumo["arquivos_incompletos_removidos"]:
        print(f"  Arquivos incompletos removidos: {len(resumo['arquivos_incompletos_removidos'])}")
    print(f"  Duração: {resumo['duracao_s']} s")
    for nome, info in resumo["tarefas"].items():
        detalhes = []
        if info.get("situacao"):
            detalhes.append(info["situacao"])
        if info.get("registros_lidos") is not None:
            detalhes.append(f"lidos={info['registros_lidos']}")
            detalhes.append(f"observações={info['observacoes']}")
            detalhes.append(f"rejeitados={sum((info.get('rejeitados') or {}).values())}")
            detalhes.append(f"duplicatas={info.get('duplicatas_exatas_removidas')}")
        if info.get("diferencas"):
            detalhes.append(f"diferenças={info['diferencas']}")
        if info.get("erro"):
            detalhes.append(f"ERRO: {info['erro']}")
        print(f"  {nome:<28} {info['status']:<12} {' | '.join(detalhes)}")

"""Rastreabilidade: liga cada observação à resposta do IpeaData que a originou.

Cada arquivo bruto de ``data/raw/ipeadata`` tem um ``.meta.json`` (URL, status HTTP, horário,
bytes e SHA-256 do corpo) gravado pela coleta. Aqui esses metadados viram linhas de
``snapshots_origem`` e as observações são ligadas a elas por ``snapshot_id``.

Nada aqui marca algo como validado: o status nasce ``nao_validado`` e só a auditoria
(``banco/auditoria.py``), depois de comparar com as respostas ao vivo do IpeaData, o altera.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from coleta.armazenamento import ler_json
from coleta.config import Diretorios
from coleta.procedencia import codigo_na_url, host_autorizado, url_territorios_valida

logger = logging.getLogger(__name__)


def caminho_meta(arquivo_bruto: str) -> str:
    return arquivo_bruto.replace(".json.gz", ".meta.json")


def ler_meta_bruto(dirs: Diretorios, arquivo_bruto: str) -> dict[str, Any] | None:
    return ler_json(dirs.raiz / caminho_meta(arquivo_bruto))


def _instante(valor: str | None) -> datetime | None:
    return datetime.fromisoformat(valor) if valor else None


def registrar_snapshot(
    con: Connection,
    dirs: Diretorios,
    arquivo_bruto: str,
    tipo: str = "serie",
    serie_codigo: str | None = None,
    execucao_coleta_id: str | None = None,
    serie_atualizada_em: str | None = None,
    metadados: dict[str, Any] | None = None,
    arquivos: list[str] | None = None,
) -> int | None:
    """Registra (ou atualiza) o snapshot de um arquivo bruto. Devolve o id, ou ``None`` se não for possível.

    Não é possível quando o ``.meta.json`` não existe ou a URL registrada não é do IpeaData:
    nesse caso a observação fica sem snapshot e, portanto, nunca será validada.
    """
    meta = ler_meta_bruto(dirs, arquivo_bruto)
    if not meta:
        logger.warning("Sem .meta.json para %s: observações dele não poderão ser validadas", arquivo_bruto,
                       extra={"evento": "snapshot_sem_meta", "arquivo": arquivo_bruto})
        return None
    url = meta.get("url") or ""
    if tipo == "serie":
        serie_codigo = serie_codigo or codigo_na_url(url)
    ok_url = host_autorizado(url) and (url_territorios_valida(url) if tipo == "territorios" else bool(codigo_na_url(url)))
    if not ok_url:
        logger.error("URL fora do IpeaData em %s: %s", arquivo_bruto, url, extra={"evento": "snapshot_url_invalida"})
        return None
    paginas = arquivos or [arquivo_bruto]
    return con.execute(text("""
        INSERT INTO snapshots_origem (tipo, serie_codigo, arquivo_bruto, arquivos, paginas, url, status_http, sha256,
                                      bytes, coletado_em, execucao_coleta_id, serie_atualizada_em, metadados)
        VALUES (:tipo, :serie, :arquivo, CAST(:arquivos AS jsonb), :paginas, :url, :status, :sha, :bytes, :coletado,
                :execucao, :atualizada, CAST(:metadados AS jsonb))
        ON CONFLICT ON CONSTRAINT uq_snapshots_origem_arquivo_bruto DO UPDATE SET
            -- Se o arquivo mudou desde o registro, a verificação anterior deixa de valer.
            status_procedencia = CASE WHEN snapshots_origem.sha256 <> EXCLUDED.sha256
                                      THEN 'nao_validado' ELSE snapshots_origem.status_procedencia END,
            verificado_em = CASE WHEN snapshots_origem.sha256 <> EXCLUDED.sha256 THEN NULL ELSE snapshots_origem.verificado_em END,
            sha256 = EXCLUDED.sha256, bytes = EXCLUDED.bytes, url = EXCLUDED.url
        RETURNING id
    """), {
        "tipo": tipo, "serie": serie_codigo, "arquivo": arquivo_bruto,
        "arquivos": _json(paginas), "paginas": len(paginas), "url": url, "status": meta.get("status_http"),
        "sha": meta.get("sha256"), "bytes": meta.get("bytes"), "coletado": _instante(meta.get("coletado_em_utc")),
        "execucao": execucao_coleta_id, "atualizada": _instante(serie_atualizada_em) if serie_atualizada_em else None,
        "metadados": _json(metadados) if metadados else None,
    }).scalar_one()


def _json(valor: Any) -> str:
    import json

    return json.dumps(valor, ensure_ascii=False, default=str)


def vincular_snapshots(con: Connection, serie_id: int | None = None) -> int:
    """Liga ao snapshot as observações sem vínculo, pelo ``arquivo_bruto`` e pela série.

    Um gatilho do banco impede ligar uma observação a snapshot de outra série.
    """
    filtro = "AND r.serie_id = :serie" if serie_id else ""
    return con.execute(text(f"""
        UPDATE registros_emprego r SET snapshot_id = sn.id
        FROM snapshots_origem sn JOIN series_indicadores s ON s.codigo = sn.serie_codigo
        WHERE sn.tipo = 'serie' AND sn.arquivo_bruto = r.arquivo_bruto AND s.id = r.serie_id
          AND r.snapshot_id IS NULL {filtro}
    """), {"serie": serie_id}).rowcount


def snapshot_territorios(estado_checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    """Snapshot do cadastro de municípios da última coleta concluída (do checkpoint)."""
    conclusao = ((estado_checkpoint.get("tarefas") or {}).get("territorios") or {}).get("ultima_conclusao") or {}
    return (conclusao.get("resultado") or {}).get("territorios_ipeadata")

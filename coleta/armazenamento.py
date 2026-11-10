"""Persistência em disco com escrita atômica, hashes e partições por ano.

Regra geral: todo arquivo é escrito primeiro em ``<nome>.tmp`` e só então
renomeado com ``os.replace`` (atômico no mesmo volume). Um arquivo final
nunca fica pela metade; sobras ``.tmp``/``.part`` de execuções interrompidas
são detectadas e removidas por ``limpar_incompletos``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from coleta import esquema

logger = logging.getLogger(__name__)

SUFIXOS_INCOMPLETOS = (".tmp", ".part")
_PARTICAO_ANO = re.compile(r"^ano=(\d{4})\.csv$")


def _temporario(caminho: Path) -> Path:
    return caminho.with_name(caminho.name + ".tmp")


def substituir(
    origem: Path, destino: Path, tentativas: int = 10, espera: Callable[[float], None] = time.sleep
) -> None:
    """``os.replace`` tolerante a bloqueios momentâneos no Windows.

    Sincronizadores (OneDrive) e antivírus seguram por instantes arquivos
    recém-gravados, e o rename falha com "Acesso negado". A troca continua
    atômica; só é repetida com espera crescente (até ~5 s no total).
    """
    for tentativa in range(1, tentativas + 1):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if tentativa == tentativas:
                raise
            logger.debug("Destino bloqueado (%s); nova tentativa %d", destino, tentativa)
            espera(0.05 * 2 ** min(tentativa, 6))


def escrever_bytes_atomico(caminho: Path, conteudo: bytes) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = _temporario(caminho)
    with open(temporario, "wb") as arquivo:
        arquivo.write(conteudo)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    substituir(temporario, caminho)
    return caminho


def salvar_json(objeto: Any, caminho: Path) -> Path:
    texto = json.dumps(objeto, ensure_ascii=False, indent=2, default=str)
    return escrever_bytes_atomico(caminho, texto.encode("utf-8"))


def ler_json(caminho: Path, padrao: Any = None) -> Any:
    if not caminho.exists():
        return padrao
    return json.loads(caminho.read_text(encoding="utf-8"))


def anexar_jsonl(caminho: Path, objeto: dict[str, Any]) -> None:
    """Acrescenta uma linha a um registro JSONL (histórico só cresce)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(objeto, ensure_ascii=False, default=str) + "\n")


def ler_jsonl(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.exists():
        return []
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip()]


def exportar_csv(df: pd.DataFrame, caminho: Path) -> Path:
    """CSV UTF-8, separador vírgula, datas ISO, gravado de forma atômica."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = _temporario(caminho)
    df.to_csv(temporario, index=False, encoding="utf-8", date_format="%Y-%m-%d", lineterminator="\n")
    substituir(temporario, caminho)
    logger.info("CSV gravado: %s (%d linhas)", caminho, len(df), extra={"evento": "csv_gravado", "linhas": len(df)})
    return caminho


def sha256_arquivo(caminho: Path, descomprimir: bool = False) -> str:
    """SHA-256 do arquivo (ou do conteúdo descomprimido, para .gz)."""
    hash_ = hashlib.sha256()
    abrir = gzip.open if descomprimir else open
    with abrir(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            hash_.update(bloco)
    return hash_.hexdigest()


def limpar_incompletos(diretorios: Iterable[Path]) -> list[str]:
    """Remove sobras de escritas interrompidas e devolve o que foi removido."""
    removidos = []
    for base in diretorios:
        if not base.exists():
            continue
        for caminho in base.rglob("*"):
            if caminho.is_file() and caminho.name.endswith(SUFIXOS_INCOMPLETOS):
                caminho.unlink()
                removidos.append(str(caminho))
                logger.warning(
                    "Arquivo incompleto removido: %s", caminho,
                    extra={"evento": "arquivo_incompleto_removido", "arquivo": str(caminho)},
                )
    return removidos


def carimbo(iso: str) -> str:
    """``2026-10-25T16:01:59+00:00`` -> ``20261025T160159Z`` (para nomes de arquivo)."""
    return iso.replace(":", "").replace("-", "").replace("+0000", "Z")


def relativo(caminho: Path, raiz: Path) -> str:
    try:
        return caminho.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return str(caminho)


# --- Partições por ano -----------------------------------------------------------

def particoes_existentes(diretorio: Path) -> dict[int, Path]:
    if not diretorio.exists():
        return {}
    return {
        int(m.group(1)): caminho
        for caminho in diretorio.iterdir()
        if (m := _PARTICAO_ANO.match(caminho.name))
    }


def escrever_particoes(
    df: pd.DataFrame,
    diretorio: Path,
    colunas: tuple[esquema.Coluna, ...],
    anos: Iterable[int] | None = None,
    remover_obsoletas: bool = False,
) -> list[dict[str, Any]]:
    """Grava ``ano=AAAA.csv`` para cada ano (ou só para ``anos``).

    ``remover_obsoletas`` apaga partições de anos que não existem mais em
    ``df`` (usado na carga completa, que representa a fonte inteira).
    """
    df = esquema.conformar(df, colunas)
    anos_alvo = sorted(set(df["ano"].dropna().astype(int)) if anos is None else set(anos))
    gravados = []
    for ano in anos_alvo:
        parte = df[df["ano"] == ano].sort_values(list(esquema.CHAVE_OBSERVACAO))
        caminho = diretorio / f"ano={ano}.csv"
        if parte.empty:
            if caminho.exists():
                caminho.unlink()
            continue
        exportar_csv(parte, caminho)
        gravados.append({"caminho": caminho, "ano": ano, "linhas": len(parte), "sha256": sha256_arquivo(caminho)})
    if remover_obsoletas:
        for ano, caminho in particoes_existentes(diretorio).items():
            if ano not in anos_alvo:
                caminho.unlink()
                logger.info("Partição obsoleta removida: %s", caminho, extra={"evento": "particao_removida"})
    return gravados


def ler_particoes(diretorio: Path, colunas: tuple[esquema.Coluna, ...]) -> pd.DataFrame:
    partes = [esquema.ler_csv(caminho, colunas) for _, caminho in sorted(particoes_existentes(diretorio).items())]
    if not partes:
        return esquema.conformar(pd.DataFrame(columns=esquema.nomes(colunas)), colunas)
    return pd.concat(partes, ignore_index=True)

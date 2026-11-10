"""Leitura em fluxo de respostas OData gravadas em disco (``.json.gz``).

Usa ``ijson`` (backend C ``yajl2_c``), que percorre o JSON sem montar o
documento inteiro na memória: os registros saem um a um e são agrupados em
lotes de tamanho configurável.
"""

from __future__ import annotations

import gzip
import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ijson

from coleta.ipea_client import IpeaResponseError

_AUSENTE = object()


@dataclass(frozen=True)
class InfoDocumento:
    proxima_pagina: str | None


class DocumentoOData:
    """Um documento OData (uma página) gravado em ``caminho``."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho

    def _itens(self, prefixo: str) -> Iterator[Any]:
        with gzip.open(self.caminho, "rb") as arquivo:
            try:
                yield from ijson.items(arquivo, prefixo, use_float=True)
            except ijson.JSONError as exc:
                raise IpeaResponseError(f"JSON inválido em {self.caminho.name}: {exc}") from exc
            except (OSError, EOFError) as exc:  # gzip corrompido ou truncado
                raise IpeaResponseError(f"Arquivo corrompido {self.caminho.name}: {exc}") from exc

    def _primeiro(self, prefixo: str) -> Any:
        """Primeiro item do prefixo, fechando o arquivo logo em seguida."""
        gerador = self._itens(prefixo)
        try:
            return next(gerador, _AUSENTE)
        finally:
            gerador.close()

    def validar(self) -> InfoDocumento:
        """Confere a estrutura OData e devolve o link da próxima página, se houver.

        Cada verificação é uma varredura feita em C pelo ijson; nenhuma monta
        a lista de registros.
        """
        erro = self._primeiro("error")
        if erro is not _AUSENTE:
            mensagem = erro.get("message") if isinstance(erro, dict) else erro
            raise IpeaResponseError(f"API retornou erro em {self.caminho.name}: {mensagem}")
        if self._primeiro("value.item") is _AUSENTE:
            # Sem registros: só é válido se existir uma lista "value" vazia.
            if not isinstance(self._primeiro("value"), list):
                raise IpeaResponseError(f"Campo 'value' ausente ou inválido em {self.caminho.name}")
        proxima = self._primeiro("@odata.nextLink")
        return InfoDocumento(proxima_pagina=proxima if isinstance(proxima, str) else None)

    def registros(self) -> Iterator[dict[str, Any]]:
        yield from self._itens("value.item")

    def lotes(self, tamanho: int) -> Iterator[list[dict[str, Any]]]:
        if tamanho < 1:
            raise ValueError("tamanho do lote deve ser >= 1")
        iterador = self.registros()
        while lote := list(itertools.islice(iterador, tamanho)):
            yield lote


def lotes_de_paginas(caminhos: list[Path], tamanho: int) -> Iterator[list[dict[str, Any]]]:
    """Lotes de todas as páginas de um snapshot, na ordem em que foram baixadas."""
    for caminho in caminhos:
        yield from DocumentoOData(caminho).lotes(tamanho)

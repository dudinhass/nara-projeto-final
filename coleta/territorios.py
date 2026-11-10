"""Cadastro de municípios a partir do IpeaData (entidade ``Territorios``).

Regra do projeto: todos os dados vêm do IpeaData, inclusive o cadastro territorial. O código de
7 dígitos publicado no IpeaData em ``TERCODIGO`` é o código municipal do IBGE; nenhuma lista
externa é consultada. A validação é estrutural e roda sobre a própria resposta:

* todos os códigos têm 7 dígitos, pertencem à UF pedida e não se repetem;
* todos os nomes estão preenchidos;
* a quantidade confere com o total esperado da UF (``ConfigColeta.total_municipios_esperado``,
  uma constante do projeto, não um dado importado).

Além disso, o pipeline rejeita qualquer observação municipal cujo código não esteja neste cadastro.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from coleta import esquema

logger = logging.getLogger(__name__)


class ErroTerritorial(RuntimeError):
    """A validação territorial reprovou o cadastro."""


def codigo_municipal_valido(codigo: str, codigo_uf: str) -> bool:
    return bool(re.fullmatch(r"\d{7}", codigo or "")) and codigo.startswith(codigo_uf)


def validar_cadastro(
    registros: list[dict[str, Any]], codigo_uf: str, total_esperado: int | None, politica: str
) -> tuple[dict[str, str], list[str]]:
    """Valida os registros de ``Territorios`` e devolve ``(codigo -> nome, problemas)``.

    Na política ``estrita`` qualquer problema levanta ``ErroTerritorial``.
    """
    municipios: dict[str, str] = {}
    problemas: list[str] = []
    for r in registros:
        codigo, nome = str(r.get("TERCODIGO") or "").strip(), str(r.get("TERNOME") or "").strip()
        if r.get("NIVNOME") not in (None, "Municípios"):
            problemas.append(f"Território {codigo!r} com nível {r.get('NIVNOME')!r} no cadastro de municípios")
        elif not codigo_municipal_valido(codigo, codigo_uf):
            problemas.append(f"Código municipal inválido para a UF {codigo_uf}: {codigo!r}")
        elif not nome:
            problemas.append(f"Município {codigo} sem nome no IpeaData")
        elif codigo in municipios:
            problemas.append(f"Código repetido no cadastro: {codigo}")
        else:
            municipios[codigo] = nome
    if total_esperado is not None and len(municipios) != total_esperado:
        problemas.append(f"O cadastro do IpeaData tem {len(municipios)} municípios válidos; esperado {total_esperado}")
    for problema in problemas:
        logger.warning(problema, extra={"evento": "validacao_territorial"})
    if problemas and politica == "estrita":
        raise ErroTerritorial("; ".join(problemas))
    return municipios, problemas


def municipios_dataframe(
    registros: list[dict[str, Any]], municipios: dict[str, str], uf_sigla: str, codigo_uf: str
) -> pd.DataFrame:
    """Tabela de municípios; só entram códigos que passaram na validação."""
    por_codigo = {str(r.get("TERCODIGO")): r for r in registros}
    linhas = [
        {
            "cod_ibge": codigo,
            "municipio": nome,
            "uf": uf_sigla,
            "cod_uf": codigo_uf,
            "nome_ipeadata": nome,
            "capital": por_codigo[codigo].get("TERCAPITAL"),
            "area_km2": por_codigo[codigo].get("TERAREA"),
            "presente_ipeadata": True,  # o cadastro inteiro vem do IpeaData
        }
        for codigo, nome in sorted(municipios.items())
    ]
    return esquema.conformar(pd.DataFrame(linhas, columns=esquema.nomes(esquema.MUNICIPIO)), esquema.MUNICIPIO)

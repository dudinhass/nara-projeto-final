"""Verificações de procedência: a série, seus metadados e a URL de coleta precisam corresponder.

Estas funções são puras (sem rede nem banco) e servem tanto ao pipeline de coleta, que recusa
séries sem procedência ao baixá-las, quanto à auditoria do PostgreSQL.

O critério nunca é só "a URL contém ipeadata.gov.br": a URL tem de pertencer a um host
autorizado **e** apontar exatamente para a série esperada, os metadados da série precisam
corresponder ao que está configurado, e cada observação precisa carregar o código da série.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

from coleta.config import HOSTS_AUTORIZADOS, SerieConfig

PADRAO_VALORES = re.compile(r"^/api/odata4/ValoresSerie\(SERCODIGO='([A-Za-z0-9_ ]+)'\)$")
PADRAO_METADADOS = re.compile(r"^/api/odata4/Metadados\('([A-Za-z0-9_ ]+)'\)$")
PADRAO_TERRITORIOS = re.compile(r"^/api/odata4/Territorios$")


def host_autorizado(url: str, hosts: tuple[str, ...] = HOSTS_AUTORIZADOS) -> bool:
    partes = urlsplit(url or "")
    return partes.scheme == "https" and partes.hostname in hosts and not (partes.username or partes.password)


def codigo_na_url(url: str, tipo: str = "valores") -> str | None:
    """Código da série que a URL consulta (``None`` se não for uma URL esperada do IpeaData)."""
    caminho = unquote(urlsplit(url or "").path)
    correspondencia = (PADRAO_VALORES if tipo == "valores" else PADRAO_METADADOS).match(caminho)
    return correspondencia.group(1) if correspondencia else None


def url_territorios_valida(url: str, hosts: tuple[str, ...] = HOSTS_AUTORIZADOS) -> bool:
    return host_autorizado(url, hosts) and bool(PADRAO_TERRITORIOS.match(urlsplit(url).path))


def url_corresponde_a_serie(url: str, codigo: str, hosts: tuple[str, ...] = HOSTS_AUTORIZADOS) -> bool:
    """A URL é do IpeaData, é a consulta de valores e é da série ``codigo`` (e de nenhuma outra)."""
    return host_autorizado(url, hosts) and codigo_na_url(url, "valores") == codigo


def verificar_metadados(serie: SerieConfig, meta: dict[str, Any] | None) -> list[str]:
    """Problemas encontrados entre os metadados do IpeaData e a configuração da série."""
    if not meta:
        return [f"série {serie.codigo} não existe no IpeaData"]
    problemas = []
    if meta.get("SERCODIGO") != serie.codigo:
        problemas.append(f"código nos metadados ({meta.get('SERCODIGO')!r}) difere do solicitado ({serie.codigo!r})")
    if meta.get("SERNUMERICA") is not True:
        problemas.append("série não numérica")
    if serie.base_ipeadata and meta.get("BASNOME") != serie.base_ipeadata:
        problemas.append(f"base {meta.get('BASNOME')!r}; esperado {serie.base_ipeadata!r}")
    if (meta.get("PERNOME") or "").strip().lower() != "mensal":
        problemas.append(f"periodicidade {meta.get('PERNOME')!r}; esperado 'Mensal'")
    if (meta.get("UNINOME") or "").strip() != "Pessoa":
        problemas.append(f"unidade {meta.get('UNINOME')!r}; esperado 'Pessoa'")
    return problemas


def comparar_metadados(armazenado: dict[str, Any], vivo: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Campos descritivos que diferem entre o que o banco guarda e o que o IpeaData publica agora."""
    campos = {"nome": "SERNOME", "periodicidade": "PERNOME", "unidade": "UNINOME", "base_ipeadata": "BASNOME"}
    diferencas = {}
    for campo, chave in campos.items():
        a, v = (armazenado.get(campo) or "").strip(), (vivo.get(chave) or "").strip()
        if a != v:
            diferencas[campo] = (a, v)
    return diferencas

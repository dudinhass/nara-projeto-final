"""Investigação do catálogo do IpeaData: existência, metadados e perfil das séries."""

from __future__ import annotations

import logging
import re
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from coleta.config import (
    MUNICIPIOS_TESTE,
    NIVEL_MUNICIPIOS,
    PADROES_BUSCA_CODIGO,
    PADROES_BUSCA_FONTE,
    PADROES_BUSCA_NOME,
)
from coleta.ipea_client import IpeaAPIError, IpeaClient
from coleta.leitor_odata import DocumentoOData

logger = logging.getLogger(__name__)


def normalizar_texto(texto: str | None) -> str:
    """Minúsculas e sem acentos, para busca tolerante."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return decomposto.encode("ascii", "ignore").decode("ascii").lower()


def buscar_series(
    catalogo: Iterable[dict[str, Any]],
    padroes_nome: Iterable[str] = PADROES_BUSCA_NOME,
    padroes_codigo: Iterable[str] = PADROES_BUSCA_CODIGO,
    padroes_fonte: Iterable[str] = PADROES_BUSCA_FONTE,
) -> list[dict[str, Any]]:
    """Filtra o catálogo localmente por nome, código ou fonte.

    A API não suporta ``contains`` em ``$filter``. Encontrar uma série aqui
    não a torna adequada: a adequação depende do perfil territorial.
    """
    regex_nome = re.compile("|".join(padroes_nome))
    regex_codigo = re.compile("|".join(padroes_codigo))
    regex_fonte = re.compile("|".join(padroes_fonte))
    encontrados = [
        meta
        for meta in catalogo
        if regex_nome.search(normalizar_texto(meta.get("SERNOME")))
        or regex_codigo.search(meta.get("SERCODIGO") or "")
        or regex_fonte.search(normalizar_texto(f"{meta.get('FNTSIGLA')} {meta.get('FNTNOME')}"))
    ]
    return sorted(encontrados, key=lambda meta: meta["SERCODIGO"])


def situacao_serie(meta: dict[str, Any]) -> str:
    """Interpreta ``SERSTATUS`` ('A'/'I'); a base Regional não preenche o campo."""
    if meta.get("SERSTATUS") == "I" or "INATIVA" in (meta.get("SERNOME") or "").upper():
        return "inativa"
    if meta.get("SERSTATUS") == "A":
        return "ativa"
    return "não informado"


def resumir_metadados(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "codigo": meta.get("SERCODIGO"),
        "nome": meta.get("SERNOME"),
        "base": meta.get("BASNOME"),
        "fonte_sigla": meta.get("FNTSIGLA"),
        "fonte_nome": meta.get("FNTNOME"),
        "fonte_url": meta.get("FNTURL"),
        "periodicidade": meta.get("PERNOME"),
        "unidade": meta.get("UNINOME"),
        "multiplicador": (meta.get("MULNOME") or "").strip() or None,
        "situacao": situacao_serie(meta),
        "ultima_atualizacao": meta.get("SERATUALIZACAO"),
        "numerica": meta.get("SERNUMERICA"),
        "tema": meta.get("TEMCODIGO"),
        "pais": meta.get("PAICODIGO"),
    }


def verificar_candidatas(cliente: IpeaClient, codigos: Iterable[str]) -> list[dict[str, Any]]:
    """Consulta ``Metadados('X')`` para cada código e registra se existe."""
    resultado = []
    for codigo in codigos:
        meta = cliente.metadados(codigo)
        if meta is None:
            logger.warning("Série %s não existe no IpeaData", codigo)
            resultado.append({"codigo": codigo, "existe": False})
        else:
            resultado.append({"existe": True, **resumir_metadados(meta)})
    return resultado


def perfil_valores(registros: Iterable[dict[str, Any]], codigo_uf: str = "21") -> dict[str, Any]:
    """Resume cobertura temporal e territorial percorrendo os registros uma vez."""
    niveis: dict[str, dict[str, Any]] = {}
    municipios_uf: set[str] = set()
    total = nulos = 0
    for registro in registros:
        total += 1
        nulos += registro.get("VALVALOR") is None
        nivel = registro.get("NIVNOME") or "(sem nível: série nacional)"
        acumulado = niveis.setdefault(nivel, {"registros": 0, "territorios": set(), "datas": set()})
        acumulado["registros"] += 1
        acumulado["territorios"].add(registro.get("TERCODIGO"))
        acumulado["datas"].add(str(registro.get("VALDATA", ""))[:10])
        if nivel == NIVEL_MUNICIPIOS and str(registro.get("TERCODIGO", "")).startswith(codigo_uf):
            municipios_uf.add(str(registro.get("TERCODIGO")))

    resumo_niveis = {}
    for nivel, acumulado in sorted(niveis.items()):
        datas = sorted(acumulado["datas"])
        resumo_niveis[nivel] = {
            "registros": acumulado["registros"],
            "territorios": len(acumulado["territorios"]),
            "periodos": len(datas),
            "data_inicio": datas[0] if datas else None,
            "data_fim": datas[-1] if datas else None,
        }
    return {
        "total_registros": total,
        "valores_nulos": nulos,
        "niveis": resumo_niveis,
        "tem_dados_municipais": NIVEL_MUNICIPIOS in niveis,
        "municipios_uf_com_registros": len(municipios_uf),
        "municipios_teste_presentes": {codigo: codigo in municipios_uf for codigo in MUNICIPIOS_TESTE},
        "adequada_para_analise_municipal": NIVEL_MUNICIPIOS in niveis and len(municipios_uf) > 0,
    }


def perfil_por_download(cliente: IpeaClient, codigo: str, pasta: Path, codigo_uf: str) -> dict[str, Any]:
    """Baixa a série para disco e traça o perfil em fluxo."""
    destino = pasta / f"{codigo}.json.gz"
    download = cliente.baixar_para_arquivo(cliente.caminho_valores(codigo), destino)
    documento = DocumentoOData(destino)
    info = documento.validar()
    perfil = perfil_valores(documento.registros(), codigo_uf)
    perfil.update({"bytes": download.bytes, "paginacao_detectada": info.proxima_pagina is not None})
    destino.unlink(missing_ok=True)
    return perfil


def investigar(cliente: IpeaClient, candidatas: Iterable[str], codigo_uf: str = "21") -> dict[str, Any]:
    """Executa a investigação completa e devolve um relatório serializável.

    1. Verifica os códigos candidatos individualmente.
    2. Baixa o catálogo e busca séries relacionadas por nome, código e fonte.
    3. Baixa os valores de cada série relacionada e traça seu perfil.
    """
    relatorio: dict[str, Any] = {"candidatas": verificar_candidatas(cliente, candidatas)}
    catalogo = cliente.catalogo_metadados()
    relacionadas = buscar_series(catalogo)
    relatorio["catalogo_total_series"] = len(catalogo)
    relatorio["series_relacionadas"] = []
    logger.info("%d séries relacionadas encontradas em %d", len(relacionadas), len(catalogo))

    with tempfile.TemporaryDirectory(prefix="investigacao_ipea_") as temporario:
        for meta in relacionadas:
            resumo = resumir_metadados(meta)
            try:
                resumo["perfil"] = perfil_por_download(cliente, meta["SERCODIGO"], Path(temporario), codigo_uf)
            except IpeaAPIError as exc:
                logger.error("Falha ao obter valores de %s: %s", meta["SERCODIGO"], exc)
                resumo["perfil"] = None
                resumo["erro"] = str(exc)
            relatorio["series_relacionadas"].append(resumo)
    return relatorio

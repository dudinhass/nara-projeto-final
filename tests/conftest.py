"""Fixtures compartilhadas.

Os dados aqui são **sintéticos**, criados só para exercitar o código: três
municípios do MA, um de outra UF e níveis agregados, no mesmo formato
JSON devolvido pela API do IpeaData.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from coleta.config import ConfigAPI, ConfigColeta, Diretorios, SERIES
from coleta.ipea_client import Download, IpeaClient, RespostaAPI
from coleta.pipeline import Pipeline

BASE = "https://api.teste/odata4/"  # só para testar o IpeaClient real com respostas simuladas
# Endereço que a fonte simulada informa como origem; tem o formato real do IpeaData (nada é acessado).
URL_IPEA = "https://www.ipeadata.gov.br/api/odata4/"
OFICIAIS = {"2103000": "Caxias", "2105302": "Imperatriz", "2111300": "São Luís"}
M = "Municípios"


def valor(serie: str, data: str, v: Any, nivel: str, ter: str) -> dict[str, Any]:
    """Registro no formato devolvido por ValoresSerie."""
    return {"SERCODIGO": serie, "VALDATA": f"{data}T00:00:00-03:00", "VALVALOR": v, "NIVNOME": nivel, "TERCODIGO": ter}


def metadados(codigo: str, atualizacao: str = "2026-10-05T16:00:00-03:00", periodicidade: str = "Mensal") -> dict[str, Any]:
    return {
        "SERCODIGO": codigo, "SERNOME": f"Série de teste {codigo}",
        "BASNOME": "Macroeconômico" if codigo.startswith("CAGED12") else "Regional", "FNTSIGLA": "MTE/Caged",
        "FNTNOME": "Ministério do Trabalho", "FNTURL": "www.mte.gov.br", "PERNOME": periodicidade, "UNINOME": "Pessoa",
        "MULNOME": " ", "SERSTATUS": None, "SERATUALIZACAO": atualizacao, "SERNUMERICA": True,
    }


def serie_municipal(codigo: str, base: int) -> list[dict[str, Any]]:
    """3 meses × 3 municípios do MA, com uma lacuna (Caxias, fev) e um zero."""
    registros = []
    for i, mes in enumerate(("2020-01-01", "2020-02-01", "2020-03-01")):
        registros.append(valor(codigo, mes, base + i, M, "2111300"))
        registros.append(valor(codigo, mes, 0 if i == 2 else base // 10, M, "2105302"))
        if mes != "2020-02-01":
            registros.append(valor(codigo, mes, 5, M, "2103000"))
        registros.append(valor(codigo, mes, 999, M, "2211001"))  # Piauí: fora do escopo
        registros.append(valor(codigo, mes, 1000 + i, "Estados", "21"))
        registros.append(valor(codigo, mes, 2000 + i, "Estados", "22"))
        registros.append(valor(codigo, mes, 50000 + i, "Brasil", "0"))
        registros.append(valor(codigo, mes, 7000, "Regiões", "2"))
    return registros


def documento(registros: list[dict[str, Any]], proxima: str | None = None) -> dict[str, Any]:
    doc: dict[str, Any] = {"@odata.context": "teste", "value": registros}
    if proxima:
        doc["@odata.nextLink"] = proxima
    return doc


class FakeCliente:
    """Substitui o IpeaClient no pipeline, servindo documentos em memória.

    ``paginas[codigo]`` é uma lista de listas de registros (uma por página).
    ``falhas[codigo]`` é uma exceção levantada no próximo download da série.
    O estado é compartilhado entre instâncias criadas pela mesma fábrica.
    """

    def __init__(self, estado: dict[str, Any]) -> None:
        self.estado = estado

    def __enter__(self) -> FakeCliente:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def metadados(self, codigo: str) -> dict[str, Any] | None:
        return self.estado["metadados"].get(codigo)

    def _resposta(self, caminho: str, valores: list[dict[str, Any]]) -> RespostaAPI:
        corpo = json.dumps(documento(valores)).encode("utf-8")
        return RespostaAPI(f"{URL_IPEA}{caminho}", 200, corpo, json.loads(corpo), "2026-10-25T12:00:00+00:00", 0.01)

    def resposta_metadados(self, codigo: str) -> RespostaAPI:
        falha = self.estado["falhas"].pop(f"meta:{codigo}", None)
        if falha is not None:
            raise falha
        meta = self.estado["metadados"].get(codigo)
        return self._resposta(f"Metadados('{codigo}')", [meta] if meta else [])

    def resposta_territorios(self, codigo_uf: str) -> RespostaAPI:
        falha = self.estado["falhas"].pop("territorios", None)
        if falha is not None:
            raise falha
        return self._resposta("Territorios", self.estado["territorios"])

    def resposta_estado(self, codigo_uf: str) -> RespostaAPI:
        return self._resposta("Territorios", [{"NIVNOME": "Estados", "TERCODIGO": codigo_uf, "TERNOME": "Maranhão"}])

    def caminho_valores(self, codigo: str) -> str:
        return f"ValoresSerie(SERCODIGO='{codigo}')"

    @staticmethod
    def filtro_municipios_uf(codigo_uf: str) -> dict[str, str]:
        return {"$filter": f"startswith(TERCODIGO,'{codigo_uf}')"}

    def baixar_para_arquivo(self, caminho: str, destino: Path, params: dict[str, str] | None = None) -> Download:
        if caminho == "Territorios":
            doc, codigo = documento(self.estado["territorios"]), "Territorios"
        elif caminho.startswith("fake://"):
            codigo, pagina = caminho.removeprefix("fake://").split("/p")
            doc = self._pagina(codigo, int(pagina))
        else:
            codigo = caminho.split("'")[1]
            doc = self._pagina(codigo, 1)
        falha = self.estado["falhas"].pop(codigo, None)
        if falha is not None:
            raise falha
        self.estado["downloads"].append(codigo)
        corpo = json.dumps(doc).encode("utf-8")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(gzip.compress(corpo))
        return Download(f"{URL_IPEA}{caminho}", 200, destino, len(corpo), len(corpo),
                        hashlib.sha256(corpo).hexdigest(), "2026-10-25T12:00:00+00:00", 0.01)

    def _pagina(self, codigo: str, numero: int) -> dict[str, Any]:
        paginas = self.estado["paginas"][codigo]
        proxima = f"fake://{codigo}/p{numero + 1}" if numero < len(paginas) else None
        return documento(paginas[numero - 1], proxima)


@pytest.fixture
def estado_fonte() -> dict[str, Any]:
    return {
        "metadados": {c: metadados(c) for c in ("ADMISNC", "DESLIGNC", "CAGED12_ADMISN12")},
        "paginas": {
            "ADMISNC": [serie_municipal("ADMISNC", 100)],
            "DESLIGNC": [serie_municipal("DESLIGNC", 80)],
            "CAGED12_ADMISN12": [[valor("CAGED12_ADMISN12", m, 50000 + i, "", "")
                                  for i, m in enumerate(("2020-01-01", "2020-02-01", "2020-03-01"))]],
        },
        "territorios": [{"TERCODIGO": c, "TERNOME": n, "TERCAPITAL": c == "2111300", "TERAREA": 100.0}
                        for c, n in OFICIAIS.items()],
        "falhas": {},
        "downloads": [],
    }


@pytest.fixture
def dirs(tmp_path: Path) -> Diretorios:
    return Diretorios(raiz=tmp_path)


SERIES_TESTE = [SERIES["ADMISNC"], SERIES["DESLIGNC"], SERIES["CAGED12_ADMISN12"]]


@pytest.fixture
def criar_pipeline(dirs: Diretorios, estado_fonte: dict[str, Any]):
    def criar(modo: str = "full", **kwargs: Any) -> Pipeline:
        config = replace(
            ConfigColeta(modo=modo, tamanho_lote=4, janela_incremental_meses=2),
            **{k: kwargs.pop(k) for k in list(kwargs) if k in ConfigColeta.__dataclass_fields__},
        )
        return Pipeline(
            config, dirs, lambda: FakeCliente(estado_fonte), series=kwargs.pop("series", SERIES_TESTE), **kwargs,
        )

    return criar


def nova_atualizacao(estado: dict[str, Any], codigo: str, data: str = "2026-11-05T16:00:00-03:00") -> None:
    estado["metadados"][codigo] = metadados(codigo, data)


def copiar(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(registros)


@pytest.fixture
def esperas() -> list[float]:
    return []


@pytest.fixture
def cliente(esperas: list[float]) -> IpeaClient:
    """IpeaClient real apontando para uma URL fictícia, sem dormir."""
    config = ConfigAPI(base_url=BASE, max_tentativas_extras=2, backoff_segundos=1.0,
                       backoff_maximo_segundos=60.0, intervalo_minimo_segundos=0.0, hosts_autorizados=("api.teste",))
    with IpeaClient(config=config, espera=esperas.append) as c:
        yield c


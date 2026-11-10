"""Onde e como as observações processadas ficam em disco.

Layout (partições por fonte, indicador, série e ano):

    data/processed/<indicador>/ipeadata/<SERIE>/ano=AAAA.csv   municípios da UF
    data/processed/agregados/ipeadata/<SERIE>.csv               UF e Brasil da mesma série
    data/processed/referencia_nacional/ipeadata/<SERIE>.csv     séries só nacionais

``data/processed/manifesto.json`` registra linhas, SHA-256 e execução de
cada arquivo gravado, permitindo verificar a integridade depois.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from coleta import esquema
from coleta.armazenamento import (
    escrever_particoes,
    exportar_csv,
    ler_json,
    ler_particoes,
    relativo,
    salvar_json,
    sha256_arquivo,
)
from coleta.checkpoint import agora_utc
from coleta.config import Diretorios, SerieConfig


class RepositorioDados:
    def __init__(self, diretorios: Diretorios) -> None:
        self.dirs = diretorios
        self.caminho_manifesto = diretorios.processed / "manifesto.json"

    def dir_particoes(self, serie: SerieConfig) -> Path:
        return self.dirs.processed / serie.indicador / "ipeadata" / serie.codigo

    def arquivo_agregados(self, serie: SerieConfig) -> Path:
        return self.dirs.processed / "agregados" / "ipeadata" / f"{serie.codigo}.csv"

    def arquivo_nacional(self, serie: SerieConfig) -> Path:
        return self.dirs.processed / "referencia_nacional" / "ipeadata" / f"{serie.codigo}.csv"

    def rel(self, caminho: Path) -> str:
        return relativo(caminho, self.dirs.raiz)

    def existe(self, serie: SerieConfig) -> bool:
        if serie.escopo == "municipal":
            return any(self.dir_particoes(serie).glob("ano=*.csv"))
        return self.arquivo_nacional(serie).exists()

    def ler(self, serie: SerieConfig) -> pd.DataFrame:
        partes = []
        if serie.escopo == "municipal":
            partes.append(ler_particoes(self.dir_particoes(serie), esquema.OBSERVACAO))
            if self.arquivo_agregados(serie).exists():
                partes.append(esquema.ler_csv(self.arquivo_agregados(serie), esquema.OBSERVACAO))
        elif self.arquivo_nacional(serie).exists():
            partes.append(esquema.ler_csv(self.arquivo_nacional(serie), esquema.OBSERVACAO))
        partes = [p for p in partes if not p.empty]
        if not partes:
            return esquema.conformar(pd.DataFrame(columns=esquema.nomes(esquema.OBSERVACAO)), esquema.OBSERVACAO)
        return pd.concat(partes, ignore_index=True)

    def gravar(
        self, serie: SerieConfig, df: pd.DataFrame, anos: set[int] | None, execucao_id: str
    ) -> list[dict[str, Any]]:
        """``anos=None`` regrava tudo (e remove partições obsoletas); um
        conjunto regrava só as partições desses anos."""
        if anos is not None and not anos:
            return []
        ordem = list(esquema.CHAVE_OBSERVACAO)
        gravados = []
        if serie.escopo == "municipal":
            municipal = df[df["nivel_territorial"] == "municipio"]
            gravados += escrever_particoes(
                municipal, self.dir_particoes(serie), esquema.OBSERVACAO, anos=anos, remover_obsoletas=anos is None
            )
            agregados = esquema.conformar(df[df["nivel_territorial"] != "municipio"].sort_values(ordem), esquema.OBSERVACAO)
            destino = exportar_csv(agregados, self.arquivo_agregados(serie))
            gravados.append({"caminho": destino, "linhas": len(agregados), "sha256": sha256_arquivo(destino)})
        else:
            nacional = esquema.conformar(df.sort_values(ordem), esquema.OBSERVACAO)
            destino = exportar_csv(nacional, self.arquivo_nacional(serie))
            gravados.append({"caminho": destino, "linhas": len(nacional), "sha256": sha256_arquivo(destino)})
        gravados = [{**g, "caminho": self.rel(g["caminho"])} for g in gravados]
        self.registrar_no_manifesto(gravados, execucao_id, serie.codigo)
        if anos is None:
            self.remover_do_manifesto_ausentes()
        return gravados

    # --- Manifesto de integridade --------------------------------------------

    def manifesto(self) -> dict[str, Any]:
        return ler_json(self.caminho_manifesto, {"arquivos": {}})

    def registrar_no_manifesto(self, gravados: list[dict[str, Any]], execucao_id: str, origem: str) -> None:
        manifesto = self.manifesto()
        for item in gravados:
            manifesto["arquivos"][item["caminho"]] = {
                "linhas": item["linhas"],
                "sha256": item["sha256"],
                "execucao_id": execucao_id,
                "origem": origem,
                "gravado_em": agora_utc(),
            }
        salvar_json(manifesto, self.caminho_manifesto)

    def registrar_arquivo(self, caminho: Path, linhas: int, execucao_id: str, origem: str) -> None:
        self.registrar_no_manifesto(
            [{"caminho": self.rel(caminho), "linhas": linhas, "sha256": sha256_arquivo(caminho)}], execucao_id, origem
        )

    def remover_do_manifesto_ausentes(self) -> None:
        manifesto = self.manifesto()
        manifesto["arquivos"] = {
            caminho: info for caminho, info in manifesto["arquivos"].items() if (self.dirs.raiz / caminho).exists()
        }
        salvar_json(manifesto, self.caminho_manifesto)

    def verificar_manifesto(self) -> dict[str, Any]:
        """Confere existência e SHA-256 de cada arquivo registrado."""
        ausentes, divergentes = [], []
        arquivos = self.manifesto()["arquivos"]
        for caminho, info in arquivos.items():
            completo = self.dirs.raiz / caminho
            if not completo.exists():
                ausentes.append(caminho)
            elif sha256_arquivo(completo) != info["sha256"]:
                divergentes.append(caminho)
        return {"arquivos_verificados": len(arquivos), "ausentes": ausentes, "sha256_divergente": divergentes}

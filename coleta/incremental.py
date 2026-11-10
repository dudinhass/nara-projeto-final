"""Comparação entre a base local e um novo snapshot da fonte.

Regras da atualização incremental:

* observação nova (chave inexistente na base): incluída;
* valor revisado dentro da janela (últimos N meses do snapshot): substituído;
* valor revisado fora da janela: só é aplicado se configurado
  (``INCREMENTAL_APLICAR_REVISOES_FORA_JANELA``); caso contrário fica
  registrado como revisão pendente;
* observação que sumiu da fonte: **mantida** na base e registrada.

Toda diferença vai para um relatório de alterações, aplicada ou não.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from coleta import esquema

CHAVE = list(esquema.CHAVE_OBSERVACAO)


@dataclass
class Diferencas:
    novas: pd.DataFrame
    revisadas_na_janela: pd.DataFrame
    revisadas_fora_janela: pd.DataFrame
    ausentes_na_fonte: pd.DataFrame
    inicio_janela: date | None

    @property
    def vazia(self) -> bool:
        return all(
            df.empty
            for df in (self.novas, self.revisadas_na_janela, self.revisadas_fora_janela, self.ausentes_na_fonte)
        )

    def contagens(self) -> dict[str, int]:
        return {
            "novas": len(self.novas),
            "revisadas_na_janela": len(self.revisadas_na_janela),
            "revisadas_fora_janela": len(self.revisadas_fora_janela),
            "ausentes_na_fonte": len(self.ausentes_na_fonte),
        }


def inicio_da_janela(fim: pd.Timestamp, meses: int) -> date:
    return (fim.to_period("M") - (meses - 1)).to_timestamp().date()


def comparar(base: pd.DataFrame, nova: pd.DataFrame, janela_meses: int | None) -> Diferencas:
    """``janela_meses=None`` trata todo o período como janela (carga completa)."""
    combinado = base[CHAVE + ["valor"]].merge(
        nova[CHAVE + ["valor"]], on=CHAVE, how="outer", suffixes=("_anterior", "_novo"), indicator=True
    )
    novas = combinado[combinado["_merge"] == "right_only"]
    ausentes = combinado[combinado["_merge"] == "left_only"]
    ambas = combinado[combinado["_merge"] == "both"]
    revisadas = ambas[ambas["valor_anterior"] != ambas["valor_novo"]]

    inicio = None
    if janela_meses is not None and not nova.empty:
        inicio = inicio_da_janela(nova["data_referencia"].max(), janela_meses)
        na_janela = revisadas["data_referencia"].dt.date >= inicio
    else:
        na_janela = pd.Series(True, index=revisadas.index)
    limpar = lambda df: df.drop(columns="_merge").reset_index(drop=True)  # noqa: E731
    return Diferencas(
        novas=limpar(novas),
        revisadas_na_janela=limpar(revisadas[na_janela]),
        revisadas_fora_janela=limpar(revisadas[~na_janela]),
        ausentes_na_fonte=limpar(ausentes),
        inicio_janela=inicio,
    )


def aplicar(
    base: pd.DataFrame, nova: pd.DataFrame, dif: Diferencas, aplicar_fora_janela: bool
) -> tuple[pd.DataFrame, set[int]]:
    """Devolve a base atualizada e os anos (partições) que mudaram.

    Linhas não alteradas mantêm a proveniência original (execução e arquivo
    bruto que as gravaram).
    """
    substituir = [dif.novas, dif.revisadas_na_janela]
    if aplicar_fora_janela:
        substituir.append(dif.revisadas_fora_janela)
    chaves = pd.concat([df[CHAVE] for df in substituir], ignore_index=True)
    if chaves.empty:
        return base, set()
    marcadas = chaves.assign(_aplicar=True)
    base_restante = base.merge(marcadas, on=CHAVE, how="left")
    base_restante = base_restante[base_restante["_aplicar"].isna()].drop(columns="_aplicar")
    entrantes = nova.merge(marcadas, on=CHAVE, how="inner").drop(columns="_aplicar")
    resultado = pd.concat([base_restante, entrantes], ignore_index=True)
    anos = set(entrantes["ano"].astype(int))
    return esquema.conformar(resultado, esquema.OBSERVACAO), anos


def registro_alteracoes(dif: Diferencas, aplicar_fora_janela: bool, remover_ausentes: bool) -> pd.DataFrame:
    """Uma linha por diferença, indicando se foi aplicada."""
    partes = [
        dif.novas.assign(tipo="nova", aplicada=True),
        dif.revisadas_na_janela.assign(tipo="revisada_na_janela", aplicada=True),
        dif.revisadas_fora_janela.assign(tipo="revisada_fora_janela", aplicada=aplicar_fora_janela),
        dif.ausentes_na_fonte.assign(tipo="ausente_na_fonte", aplicada=remover_ausentes),
    ]
    colunas = ["tipo", "aplicada", *CHAVE, "valor_anterior", "valor_novo"]
    partes = [p for p in partes if not p.empty]
    if not partes:
        return pd.DataFrame(columns=colunas)
    return pd.concat(partes, ignore_index=True)[colunas]

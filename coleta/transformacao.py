"""Padronização dos registros da API no modelo de observações.

Cada registro bruto recebe um de três destinos:

* **aceito**: vira uma observação do modelo (``esquema.OBSERVACAO``);
* **excluído**: fora do escopo (outra UF, nível territorial não usado);
* **rejeitado**: dentro do escopo, mas inválido (data, valor ou código), com
  o motivo registrado.

Nada é preenchido: um período sem registro continua sem observação, e um
valor nulo é rejeitado em vez de virar zero.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from coleta import esquema
from coleta.config import FONTE_IPEADATA, NIVEL_MUNICIPIOS, SerieConfig

NIVEIS_IPEA = {"Municípios": "municipio", "Estados": "estado", "Brasil": "brasil"}
INDICADORES_CONTAGEM = ("admissoes", "desligamentos")
ORDEM_STATUS = tuple(esquema.STATUS_OBSERVACAO)


@dataclass(frozen=True)
class ContextoSerie:
    serie: SerieConfig
    metadados: dict[str, Any]
    uf_sigla: str
    codigo_uf: str
    municipios_oficiais: dict[str, str]
    coletado_em: str
    execucao_id: str
    arquivo_bruto: str

    @property
    def mensal(self) -> bool:
        return (self.metadados.get("PERNOME") or "").strip().lower() == "mensal"


@dataclass
class ResultadoProcessamento:
    observacoes: pd.DataFrame
    rejeitados: pd.DataFrame
    estatisticas: dict[str, Any]


def converter_data(bruto: Any) -> date | None:
    """``2020-01-01T00:00:00-03:00`` -> ``date(2020, 1, 1)``.

    Usa só a parte da data: converter o fuso (-03:00) para UTC deslocaria o
    mês de referência.
    """
    try:
        return date.fromisoformat(str(bruto or "")[:10])
    except ValueError:
        return None


def converter_valor(bruto: Any, indicador: str) -> tuple[int | None, str | None]:
    """Valor inteiro ou o motivo da rejeição. Nulo nunca vira zero."""
    if bruto is None:
        return None, "valor_nulo"
    if isinstance(bruto, bool):
        return None, "valor_nao_numerico"
    try:
        numero = float(bruto)
    except (TypeError, ValueError):
        return None, "valor_nao_numerico"
    if not math.isfinite(numero):
        return None, "valor_nao_numerico"
    if numero != int(numero):
        return None, "valor_nao_inteiro"
    if numero < 0 and indicador in INDICADORES_CONTAGEM:
        return None, "valor_negativo"
    return int(numero), None


def meses_entre(inicio: date, fim: date) -> list[date]:
    return [d.date() for d in pd.date_range(inicio, fim, freq="MS")]


def detectar_quedas(contagem_por_mes: dict[date, int]) -> list[date]:
    """Meses em que a fonte publicou menos territórios que nos dois vizinhos.

    Indica lacuna sistêmica da fonte (afeta muitos territórios ao mesmo
    tempo), e não ausência pontual de um município. Meses sem nenhum
    registro dentro do intervalo contam como zero.
    """
    if not contagem_por_mes:
        return []
    meses = meses_entre(min(contagem_por_mes), max(contagem_por_mes))
    valores = [contagem_por_mes.get(mes, 0) for mes in meses]
    quedas = []
    for i, valor in enumerate(valores):
        vizinhos = valores[max(0, i - 1):i] + valores[i + 1:i + 2]
        if vizinhos and valor < min(vizinhos):
            quedas.append(meses[i])
    return quedas


class Processador:
    """Acumula lotes de registros brutos de uma série."""

    def __init__(self, ctx: ContextoSerie) -> None:
        self.ctx = ctx
        self.lidos = 0
        self.lotes = 0
        self.por_nivel: Counter[str] = Counter()
        self.excluidos: Counter[str] = Counter()
        self.motivos_rejeicao: Counter[str] = Counter()
        self.registros_por_periodo: Counter[date] = Counter()
        self._aceitos: list[tuple[Any, ...]] = []
        self._rejeitados: list[dict[str, Any]] = []
        meta = ctx.metadados
        self._constantes = {
            "fonte": FONTE_IPEADATA,
            "fonte_original": meta.get("FNTSIGLA") or "",
            "serie_codigo": ctx.serie.codigo,
            "serie_nome": meta.get("SERNOME") or "",
            "indicador": ctx.serie.indicador,
            "metodologia": ctx.serie.metodologia,
            "periodicidade": meta.get("PERNOME") or "",
            "unidade": meta.get("UNINOME") or "",
            "serie_atualizada_em": meta.get("SERATUALIZACAO") or "",
            "coletado_em_utc": ctx.coletado_em,
            "execucao_id": ctx.execucao_id,
            "arquivo_bruto": ctx.arquivo_bruto,
        }

    def _territorio(self, nivel_original: str, codigo: str) -> tuple[tuple[str, str, str, str] | None, tuple[str, str] | None]:
        ctx = self.ctx
        if ctx.serie.escopo == "nacional":
            # Série nacional só pode trazer o total do Brasil. Qualquer outro nível (município, UF) é
            # rejeitado: nunca se reclassifica um dado territorial como nacional (nem o contrário).
            if nivel_original not in ("", "Brasil"):
                return None, ("rejeitado", "nivel_inesperado_em_serie_nacional")
            return ("brasil", "", "Brasil", ""), None
        nivel = NIVEIS_IPEA.get(nivel_original)
        if nivel == "municipio":
            if not codigo.startswith(ctx.codigo_uf):
                return None, ("excluido", "outra_uf")
            if not re.fullmatch(r"\d{7}", codigo):
                return None, ("rejeitado", "codigo_municipal_malformado")
            nome = ctx.municipios_oficiais.get(codigo)
            if nome is None:
                return None, ("rejeitado", "codigo_fora_do_cadastro_ipeadata")
            return ("municipio", codigo, nome, ctx.uf_sigla), None
        if nivel == "estado":
            if codigo != ctx.codigo_uf:
                return None, ("excluido", "outra_uf")
            return ("estado", codigo, ctx.uf_sigla, ctx.uf_sigla), None
        if nivel == "brasil":
            return ("brasil", "", "Brasil", ""), None
        return None, ("excluido", "nivel_nao_utilizado")

    def _rejeitar(self, registro: dict[str, Any], motivo: str) -> None:
        self.motivos_rejeicao[motivo] += 1
        self._rejeitados.append(
            {
                "motivo": motivo,
                "serie_codigo": self.ctx.serie.codigo,
                "NIVNOME": registro.get("NIVNOME"),
                "TERCODIGO": registro.get("TERCODIGO"),
                "VALDATA": registro.get("VALDATA"),
                "VALVALOR": registro.get("VALVALOR"),
                "arquivo_bruto": self.ctx.arquivo_bruto,
            }
        )

    def processar_lote(self, lote: Iterable[dict[str, Any]]) -> None:
        self.lotes += 1
        for registro in lote:
            self._processar(registro)

    def _processar(self, registro: dict[str, Any]) -> None:
        self.lidos += 1
        # Cada observação precisa carregar o código da série consultada: confere série e valores.
        if str(registro.get("SERCODIGO") or "").strip() != self.ctx.serie.codigo:
            self._rejeitar(registro, "serie_divergente")
            return
        nivel_original = str(registro.get("NIVNOME") or "").strip()
        codigo = str(registro.get("TERCODIGO") if registro.get("TERCODIGO") is not None else "").strip()
        self.por_nivel[nivel_original or "(série nacional)"] += 1
        data = converter_data(registro.get("VALDATA"))

        # Disponibilidade da série: no nível municipal de todo o país (séries
        # municipais) ou na própria série (séries nacionais).
        if data and (self.ctx.serie.escopo == "nacional" or nivel_original == NIVEL_MUNICIPIOS):
            self.registros_por_periodo[data] += 1

        territorio, destino = self._territorio(nivel_original, codigo)
        if destino:
            tipo, motivo = destino
            if tipo == "excluido":
                self.excluidos[motivo] += 1
            else:
                self._rejeitar(registro, motivo)
            return
        if data is None:
            self._rejeitar(registro, "data_invalida")
            return
        if self.ctx.mensal and data.day != 1:
            self._rejeitar(registro, "data_fora_do_padrao_mensal")
            return
        valor, motivo = converter_valor(registro.get("VALVALOR"), self.ctx.serie.indicador)
        if motivo:
            self._rejeitar(registro, motivo)
            return

        nivel, cod_ibge, nome, uf = territorio  # type: ignore[misc]
        self._aceitos.append(
            (nivel, nivel_original, codigo, cod_ibge, nome, uf, data, data.year,
             data.month if self.ctx.mensal else None, valor)
        )

    def resultado(self) -> ResultadoProcessamento:
        colunas_variaveis = [
            "nivel_territorial", "nivel_territorial_original", "cod_territorio_original", "cod_ibge",
            "territorio_nome", "uf", "data_referencia", "ano", "mes", "valor",
        ]
        df = pd.DataFrame(self._aceitos, columns=colunas_variaveis)
        for nome, valor in self._constantes.items():
            df[nome] = valor
        df = esquema.conformar(df, esquema.OBSERVACAO)
        aceitos = len(df)
        unicos, conflitantes, info_duplicatas = deduplicar(df)
        for _, linha in conflitantes.iterrows():
            self._rejeitar(
                {"NIVNOME": linha["nivel_territorial_original"], "TERCODIGO": linha["cod_territorio_original"],
                 "VALDATA": linha["data_referencia"].date().isoformat(), "VALVALOR": linha["valor"]},
                "chave_duplicada_conflitante",
            )

        disponiveis = sorted(self.registros_por_periodo)
        estatisticas = {
            "registros_lidos": self.lidos,
            "lotes": self.lotes,
            "por_nivel_original": dict(self.por_nivel),
            "excluidos": dict(self.excluidos),
            "rejeitados": dict(self.motivos_rejeicao),
            "aceitos_antes_deduplicacao": aceitos,
            **info_duplicatas,
            "observacoes": len(unicos),
            "por_nivel_territorial": unicos["nivel_territorial"].value_counts().to_dict(),
            "disponibilidade": {
                "base": "nível municipal (todo o país)" if self.ctx.serie.escopo == "municipal" else "série",
                "inicio": disponiveis[0].isoformat() if disponiveis else None,
                "fim": disponiveis[-1].isoformat() if disponiveis else None,
                "periodos": len(disponiveis),
            },
            "registros_por_periodo": {d.isoformat(): n for d, n in sorted(self.registros_por_periodo.items())},
            "lacunas_sistemicas": (
                [d.isoformat() for d in detectar_quedas(dict(self.registros_por_periodo))] if self.ctx.mensal else []
            ),
        }
        return ResultadoProcessamento(unicos.reset_index(drop=True), pd.DataFrame(self._rejeitados), estatisticas)


def processar(lotes: Iterable[list[dict[str, Any]]], ctx: ContextoSerie) -> ResultadoProcessamento:
    processador = Processador(ctx)
    for lote in lotes:
        processador.processar_lote(lote)
    return processador.resultado()


def deduplicar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Remove repetições exatas; chaves repetidas com valores diferentes saem todas.

    Duas linhas com a mesma chave natural e o mesmo valor são a mesma
    observação (mantém-se uma). Com valores diferentes não há como escolher
    sem inventar: todas são rejeitadas e reportadas.
    """
    chave = list(esquema.CHAVE_OBSERVACAO)
    exatas = df.duplicated(subset=chave + ["valor"], keep="first")
    restante = df[~exatas]
    conflito = restante.duplicated(subset=chave, keep=False)
    info = {
        "duplicatas_exatas_removidas": int(exatas.sum()),
        "chaves_conflitantes": int(restante[conflito][chave].drop_duplicates().shape[0]),
    }
    return restante[~conflito], restante[conflito], info


def status_observacao(valor: Any, disponivel: bool, coleta_ok: bool) -> str:
    if not coleta_ok:
        return "falha_coleta"
    if not disponivel:
        return "nao_disponibilizado_pela_fonte"
    if pd.isna(valor):
        return "observacao_ausente"
    return "zero_encontrado" if valor == 0 else "valor_encontrado"


@dataclass
class EntradaPainel:
    serie: SerieConfig
    observacoes: pd.DataFrame
    inicio: date | None
    fim: date | None
    coleta_ok: bool = True
    meses: set[date] = field(init=False)

    def __post_init__(self) -> None:
        self.meses = set(meses_entre(self.inicio, self.fim)) if self.inicio and self.fim else set()


def montar_painel(
    admissoes: EntradaPainel, desligamentos: EntradaPainel, municipios: pd.DataFrame
) -> pd.DataFrame:
    """Grade completa município × mês com valores, situação e saldo.

    Os meses cobrem a união das disponibilidades das duas séries. O saldo só
    é calculado quando admissões e desligamentos existem e as séries têm a
    mesma metodologia.
    """
    if admissoes.serie.metodologia != desligamentos.serie.metodologia:
        raise ValueError("Séries de metodologias diferentes não podem compor o saldo")
    meses = sorted(admissoes.meses | desligamentos.meses)
    grade = pd.MultiIndex.from_product(
        [municipios["cod_ibge"].tolist(), pd.to_datetime(meses)], names=["cod_ibge", "data_referencia"]
    ).to_frame(index=False)
    painel = grade.merge(municipios[["cod_ibge", "municipio", "uf"]], on="cod_ibge", how="left")

    for nome, entrada in (("admissoes", admissoes), ("desligamentos", desligamentos)):
        municipais = entrada.observacoes[entrada.observacoes["nivel_territorial"] == "municipio"]
        valores = municipais[["cod_ibge", "data_referencia", "valor"]].rename(columns={"valor": nome})
        painel = painel.merge(valores, on=["cod_ibge", "data_referencia"], how="left")
        disponivel = painel["data_referencia"].dt.date.isin(entrada.meses)
        painel[f"status_{nome}"] = [
            status_observacao(v, d, entrada.coleta_ok) for v, d in zip(painel[nome], disponivel)
        ]

    painel["saldo"] = painel["admissoes"] - painel["desligamentos"]
    painel["ano"] = painel["data_referencia"].dt.year
    painel["mes"] = painel["data_referencia"].dt.month
    painel["serie_admissoes"] = admissoes.serie.codigo
    painel["serie_desligamentos"] = desligamentos.serie.codigo
    painel["metodologia"] = admissoes.serie.metodologia
    painel["fonte"] = FONTE_IPEADATA
    return esquema.conformar(painel, esquema.PAINEL).sort_values(list(esquema.CHAVE_PAINEL)).reset_index(drop=True)

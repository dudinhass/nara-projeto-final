"""Consultas analíticas reutilizáveis (base para a futura API).

O SQL fica em ``database/queries/*.sql``. Regras aplicadas aqui:

* toda consulta trabalha com **uma** metodologia; admissões e desligamentos só
  são combinados quando pertencem à mesma fonte, metodologia e escopo;
* meses sem observação continuam ausentes (NULL), nunca zero; somas trazem a
  quantidade de meses que as compõem;
* só dados com procedência validada no IpeaData são lidos (views ``vw_*_validados``); o que não
  foi validado, ou é incompatível, nunca aparece;
* nenhuma taxa percentual é calculada: não há denominador oficial (estoque de
  empregos por município) na base.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from functools import lru_cache
from typing import Any

from sqlalchemy import Connection, Engine, text

from coleta.config import RAIZ_PROJETO

PASTA_SQL = RAIZ_PROJETO / "database" / "queries"
METODOLOGIA_PADRAO = "Novo Caged - sem ajuste"
COLUNAS_RANKING = ("admissoes", "desligamentos", "saldo")
ORDENS = {"desc": "DESC", "asc": "ASC"}


class ErroConsulta(ValueError):
    """Parâmetros inválidos ou combinação metodológica não permitida."""


@lru_cache(maxsize=None)
def carregar_sql(nome: str) -> str:
    return (PASTA_SQL / f"{nome}.sql").read_text(encoding="utf-8")


def competencia(valor: date | str | None) -> date | None:
    """Aceita ``date``, ``'AAAA-MM'`` ou ``'AAAA-MM-DD'``; devolve o 1º dia do mês."""
    if valor is None or isinstance(valor, date):
        return valor.replace(day=1) if isinstance(valor, date) else None
    if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", valor):
        raise ErroConsulta(f"Competência inválida: {valor!r} (use AAAA-MM)")
    return date.fromisoformat(valor[:7] + "-01")


class ConsultasEmprego:
    def __init__(self, fonte: Engine | Connection, uf: str = "MA", cod_uf: str = "21") -> None:
        self.fonte, self.uf, self.cod_uf = fonte, uf, cod_uf

    def _executar(self, sql: str, parametros: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(self.fonte, Connection):
            return [dict(l) for l in self.fonte.execute(text(sql), parametros).mappings()]
        with self.fonte.connect() as conexao:
            return [dict(l) for l in conexao.execute(text(sql), parametros).mappings()]

    # --- Validações -------------------------------------------------------------

    def _cobertura_metodologia(self, metodologia: str, escopo: str) -> tuple[date, date]:
        """Exige o par admissões/desligamentos da metodologia e devolve o período com dados."""
        linhas = self._executar(
            """
            SELECT s.indicador, min(r.data_referencia) AS inicio, max(r.data_referencia) AS fim
            FROM series_indicadores s JOIN vw_registros_validados r ON r.serie_id = s.id
            WHERE s.metodologia = :m AND s.escopo_territorial = :e AND s.indicador IN ('admissoes', 'desligamentos')
            GROUP BY s.indicador
            """,
            {"m": metodologia, "e": escopo},
        )
        if len(linhas) != 2:
            disponiveis = self._executar(
                "SELECT DISTINCT metodologia FROM series_indicadores WHERE escopo_territorial = :e ORDER BY 1",
                {"e": escopo},
            )
            raise ErroConsulta(
                f"A metodologia {metodologia!r} não tem admissões e desligamentos com dados no escopo {escopo}. "
                f"Disponíveis: {[d['metodologia'] for d in disponiveis]}"
            )
        return min(l["inicio"] for l in linhas), max(l["fim"] for l in linhas)

    def _periodo(self, inicio: Any, fim: Any, metodologia: str, escopo: str = "municipal") -> dict[str, Any]:
        cobertura = self._cobertura_metodologia(metodologia, escopo)
        inicio, fim = competencia(inicio) or cobertura[0], competencia(fim) or cobertura[1]
        if inicio > fim:
            raise ErroConsulta(f"Início ({inicio}) posterior ao fim ({fim})")
        return {"inicio": inicio, "fim": fim, "metodologia": metodologia}

    def _validar_municipios(self, codigos: Iterable[str]) -> list[str]:
        codigos = list(codigos)
        invalidos = [c for c in codigos if not re.fullmatch(r"\d{7}", c or "")]
        if invalidos:
            raise ErroConsulta(f"Códigos IBGE inválidos: {invalidos}")
        existentes = {l["cod_ibge"] for l in self._executar(
            "SELECT cod_ibge FROM vw_municipios_validados WHERE cod_ibge = ANY(CAST(:c AS text[]))", {"c": codigos})}
        faltantes = sorted(set(codigos) - existentes)
        if faltantes:
            raise ErroConsulta(f"Municípios não cadastrados ou sem procedência validada no IpeaData: {faltantes}")
        return codigos

    # --- Consultas --------------------------------------------------------------

    def cobertura_series(self) -> list[dict[str, Any]]:
        return self._executar(carregar_sql("cobertura_series"), {})

    def ultima_competencia(self, metodologia: str = METODOLOGIA_PADRAO, escopo: str = "municipal") -> date:
        return self._cobertura_metodologia(metodologia, escopo)[1]

    def movimentacao_por_municipio(
        self, inicio: Any = None, fim: Any = None, metodologia: str = METODOLOGIA_PADRAO,
        codigos: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        parametros = self._periodo(inicio, fim, metodologia)
        parametros.update(uf=self.uf, codigos=self._validar_municipios(codigos) if codigos else None)
        return self._executar(carregar_sql("movimentacao_por_municipio"), parametros)

    def _coluna_por_municipio(self, coluna: str, meses: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"cod_ibge": l["cod_ibge"], "municipio": l["municipio"], coluna: l[coluna], "meses": l[meses]}
                for l in self.movimentacao_por_municipio(**kwargs)]

    def admissoes_por_municipio(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._coluna_por_municipio("admissoes", "meses_com_admissoes", **kwargs)

    def desligamentos_por_municipio(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._coluna_por_municipio("desligamentos", "meses_com_desligamentos", **kwargs)

    def saldo_por_municipio(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._coluna_por_municipio("saldo", "meses_com_saldo", **kwargs)

    def comparar_municipios(self, codigos: Sequence[str], **kwargs: Any) -> list[dict[str, Any]]:
        if len(codigos) < 2:
            raise ErroConsulta("Informe pelo menos dois municípios para comparar")
        return self.movimentacao_por_municipio(codigos=codigos, **kwargs)

    def ranking_municipios(
        self, indicador: str = "saldo", inicio: Any = None, fim: Any = None, limite: int = 10,
        ordem: str = "desc", metodologia: str = METODOLOGIA_PADRAO,
    ) -> list[dict[str, Any]]:
        if indicador not in COLUNAS_RANKING:
            raise ErroConsulta(f"Indicador inválido para ranking: {indicador!r} (use {COLUNAS_RANKING})")
        if ordem not in ORDENS:
            raise ErroConsulta("ordem deve ser 'desc' ou 'asc'")
        if not 1 <= limite <= 1000:
            raise ErroConsulta("limite deve estar entre 1 e 1000")
        sql = carregar_sql("ranking_municipios").format(coluna=indicador, ordem=ORDENS[ordem])
        return self._executar(sql, {**self._periodo(inicio, fim, metodologia), "uf": self.uf, "limite": limite})

    def _territorio(self, cod_ibge: str | None) -> dict[str, str]:
        if cod_ibge is None:
            return {"nivel": "estado", "cod_territorio": self.cod_uf}
        return {"nivel": "municipio", "cod_territorio": self._validar_municipios([cod_ibge])[0]}

    def evolucao_mensal(
        self, cod_ibge: str | None = None, inicio: Any = None, fim: Any = None, metodologia: str = METODOLOGIA_PADRAO,
    ) -> list[dict[str, Any]]:
        """Série mensal do município (ou da UF, com ``cod_ibge=None``), com grade completa de meses."""
        parametros = {**self._periodo(inicio, fim, metodologia), **self._territorio(cod_ibge), "escopo": "municipal"}
        return self._executar(carregar_sql("evolucao_mensal"), parametros)

    def evolucao_anual(self, cod_ibge: str | None = None, metodologia: str = METODOLOGIA_PADRAO) -> list[dict[str, Any]]:
        self._cobertura_metodologia(metodologia, "municipal")
        parametros = {**self._territorio(cod_ibge), "metodologia": metodologia, "escopo": "municipal"}
        return self._executar(carregar_sql("evolucao_anual"), parametros)

    def totais_uf(self, inicio: Any = None, fim: Any = None, metodologia: str = METODOLOGIA_PADRAO) -> dict[str, Any]:
        """Total oficial da UF e soma dos municípios, por mês e no período."""
        parametros = {**self._periodo(inicio, fim, metodologia), "uf": self.uf, "cod_uf": self.cod_uf}
        mensal = self._executar(carregar_sql("totais_uf"), parametros)
        soma = lambda c: sum(l[c] for l in mensal if l[c] is not None)  # noqa: E731
        return {
            "inicio": parametros["inicio"], "fim": parametros["fim"], "metodologia": metodologia,
            "admissoes_uf": soma("admissoes_uf"), "desligamentos_uf": soma("desligamentos_uf"), "saldo_uf": soma("saldo_uf"),
            "admissoes_soma_municipios": soma("admissoes_soma_municipios"),
            "desligamentos_soma_municipios": soma("desligamentos_soma_municipios"),
            "meses": len(mensal), "mensal": mensal,
        }

    def indicadores_periodo(self, inicio: Any = None, fim: Any = None, metodologia: str = METODOLOGIA_PADRAO) -> dict[str, Any]:
        parametros = {**self._periodo(inicio, fim, metodologia), "uf": self.uf}
        return {"inicio": parametros["inicio"], "fim": parametros["fim"], "metodologia": metodologia,
                **self._executar(carregar_sql("indicadores_periodo"), parametros)[0]}

    def historico_municipio(self, cod_ibge: str, metodologia: str = METODOLOGIA_PADRAO) -> dict[str, Any]:
        cadastro = self._executar(
            "SELECT cod_ibge, nome, uf, capital, area_km2 FROM vw_municipios_validados WHERE cod_ibge = :c",
            {"c": self._validar_municipios([cod_ibge])[0]},
        )[0]
        return {
            "municipio": cadastro,
            "metodologia": metodologia,
            "mensal": self.evolucao_mensal(cod_ibge, metodologia=metodologia),
            "anual": self.evolucao_anual(cod_ibge, metodologia=metodologia),
        }

    def comparar_periodos(
        self, periodo_a: tuple[Any, Any], periodo_b: tuple[Any, Any], cod_ibge: str | None = None,
        metodologia: str = METODOLOGIA_PADRAO,
    ) -> dict[str, Any]:
        """Totais de dois períodos e a diferença absoluta (B − A). Sem variação percentual."""
        def totais(periodo: tuple[Any, Any]) -> dict[str, Any]:
            linhas = self.evolucao_mensal(cod_ibge, periodo[0], periodo[1], metodologia)
            completas = [l for l in linhas if l["situacao"] == "completo"]
            return {
                "inicio": linhas[0]["data_referencia"], "fim": linhas[-1]["data_referencia"],
                "meses_no_periodo": len(linhas), "meses_completos": len(completas),
                "admissoes": sum(l["admissoes"] for l in linhas if l["admissoes"] is not None),
                "desligamentos": sum(l["desligamentos"] for l in linhas if l["desligamentos"] is not None),
                "saldo": sum(l["saldo"] for l in completas),
            }

        a, b = totais(periodo_a), totais(periodo_b)
        return {
            "territorio": cod_ibge or self.uf, "metodologia": metodologia, "periodo_a": a, "periodo_b": b,
            "diferenca": {c: b[c] - a[c] for c in ("admissoes", "desligamentos", "saldo")},
            "periodos_comparaveis": a["meses_completos"] == a["meses_no_periodo"] and b["meses_completos"] == b["meses_no_periodo"],
        }

    def serie_nacional(
        self, indicador: str = "admissoes", metodologias: Sequence[str] = ("CAGED tradicional", METODOLOGIA_PADRAO),
    ) -> list[dict[str, Any]]:
        """Série nacional em sequência de metodologias, com a quebra identificada.

        Recusa metodologias que se sobreponham no tempo, para não somar ou
        duplicar os mesmos movimentos.
        """
        if indicador not in COLUNAS_RANKING:
            raise ErroConsulta(f"Indicador inválido: {indicador!r}")
        linhas = self._executar(carregar_sql("serie_nacional_metodologias"),
                                {"indicador": indicador, "metodologias": list(metodologias)})
        por_mes: dict[date, set[str]] = {}
        for l in linhas:
            por_mes.setdefault(l["data_referencia"], set()).add(l["metodologia"])
        sobrepostos = sorted(d for d, m in por_mes.items() if len(m) > 1)
        if sobrepostos:
            raise ErroConsulta(
                f"As metodologias {list(metodologias)} se sobrepõem em {len(sobrepostos)} meses "
                f"(ex.: {sobrepostos[0]}); escolha uma delas para esse período."
            )
        return linhas

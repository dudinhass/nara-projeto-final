"""Acesso aos cadastros e às tabelas de controle.

Os cadastros vêm dos arquivos consolidados da coleta (``data/processed/consolidado``)
e são gravados com ``INSERT ... ON CONFLICT DO UPDATE``: reexecutar não duplica.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import Connection, case, func, null, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert

from banco.modelos import ArquivoImportado, FonteDados, Municipio, SerieIndicador

# Complemento descritivo das fontes (o consolidado traz nome, papel, url e formato).
DESCRICAO_FONTES = {
    "IpeaData": {
        "sigla": "Ipea", "descricao": "Base de dados do Instituto de Pesquisa Econômica Aplicada, acessada pela API OData v4.",
        "metodologia": "Repassa as séries da fonte primária; séries municipais do Novo Caged 'sem ajuste'.",
        "atualizacao": "Por série (campo SERATUALIZACAO); verificada a cada coleta incremental.",
    },
    "MTE/Caged": {
        "sigla": "MTE", "descricao": "Origem estatística (CAGED tradicional até 2019, Novo Caged desde 2020), informada pelo IpeaData. Nunca acessada diretamente.",
        "metodologia": "Novo Caged usa eSocial, CAGED e Empregador Web; não é diretamente comparável ao CAGED tradicional.",
        "atualizacao": "Mensal (divulgação do MTE); valores passados podem ser revisados.",
    },
}

FAMILIAS = {
    "CAGED tradicional": ("caged_tradicional", None),
    "Novo Caged - sem ajuste": ("novo_caged", "sem_ajuste"),
    "Novo Caged - com ajuste": ("novo_caged", "com_ajuste"),
}


class ErroCadastro(ValueError):
    """Cadastro de origem incompatível com o banco."""


def _texto(valor: Any) -> str | None:
    return None if valor is None or pd.isna(valor) or str(valor).strip() == "" else str(valor)


def _data(valor: Any) -> date | None:
    texto = _texto(valor)
    return date.fromisoformat(texto[:10]) if texto else None


def _instante(valor: Any) -> datetime | None:
    texto = _texto(valor)
    return datetime.fromisoformat(texto) if texto else None


def _booleano(valor: Any) -> bool:
    return str(valor).strip().lower() in {"true", "1", "sim"}


def upsert_fontes(conexao: Connection, fontes: pd.DataFrame) -> dict[str, int]:
    """Grava as fontes do consolidado. Fontes que já estão no banco e saíram do consolidado
    (o legado do IBGE) permanecem, classificadas como não autorizadas: nada é apagado."""
    for linha in fontes.to_dict("records"):
        extra = DESCRICAO_FONTES.get(linha["fonte"], {})
        valores = {
            "nome": linha["fonte"], "papel": linha["papel"], "url": _texto(linha.get("url")),
            "tipo_fonte": linha["tipo_fonte"], "autorizada_para_coleta": _booleano(linha["autorizada_para_coleta"]),
            **extra,
        }
        comando = insert(FonteDados).values(**valores)
        conexao.execute(comando.on_conflict_do_update(
            index_elements=["nome"],
            set_={**{k: comando.excluded[k] for k in valores if k != "nome"}, "atualizado_em": func.now()},
        ))
    return {nome: id_ for nome, id_ in conexao.execute(select(FonteDados.nome, FonteDados.id))}


def upsert_municipios(
    conexao: Connection, municipios: pd.DataFrame, fonte_id: int, coletado_em: str | None, total_esperado: int | None,
    snapshot_id: int | None = None,
) -> int:
    """Grava o cadastro. Município cuja identidade mudou (nome, atributos ou fonte de referência) volta a
    ``nao_validado`` e passa a apontar para o novo snapshot; os demais mantêm a validação existente."""
    if total_esperado is not None and len(municipios) != total_esperado:
        raise ErroCadastro(f"O cadastro tem {len(municipios)} municípios; esperado {total_esperado}")
    if municipios["cod_ibge"].duplicated().any():
        raise ErroCadastro("Códigos IBGE repetidos no cadastro de municípios")
    linhas = [
        {
            "cod_ibge": m["cod_ibge"], "nome": m["municipio"], "uf": m["uf"], "cod_uf": m["cod_uf"],
            "nome_ipeadata": _texto(m["nome_ipeadata"]),
            "capital": None if pd.isna(m["capital"]) else bool(m["capital"]),
            "area_km2": None if pd.isna(m["area_km2"]) else round(float(m["area_km2"]), 2),
            "presente_ipeadata": bool(m["presente_ipeadata"]),
            "fonte_referencia_id": fonte_id, "referencia_coletada_em": _instante(coletado_em),
            "snapshot_id": snapshot_id,
        }
        for m in municipios.to_dict("records")
    ]
    comando = insert(Municipio)
    col = Municipio.__table__.c
    identidade = ("nome", "uf", "cod_uf", "nome_ipeadata", "capital", "area_km2", "presente_ipeadata", "fonte_referencia_id")
    mudou = tuple_(*[col[c] for c in identidade]).is_distinct_from(tuple_(*[comando.excluded[c] for c in identidade]))
    sem_snapshot = col.snapshot_id.is_(None)
    atualizar = {c: comando.excluded[c] for c in linhas[0] if c not in ("cod_ibge", "snapshot_id")}
    conexao.execute(
        comando.on_conflict_do_update(
            index_elements=["cod_ibge"],
            set_={
                **atualizar,
                "status_procedencia": case((mudou, "nao_validado"), else_=col.status_procedencia),
                "procedencia_verificada_em": case((mudou, null()), else_=col.procedencia_verificada_em),
                "snapshot_id": case((mudou | sem_snapshot, comando.excluded.snapshot_id), else_=col.snapshot_id),
                "atualizado_em": func.now(),
            },
        ),
        linhas,
    )
    return len(linhas)


def upsert_series(conexao: Connection, series: pd.DataFrame, fontes: dict[str, int]) -> dict[str, dict[str, Any]]:
    """Grava as séries e devolve ``codigo -> {id, indicador, metodologia, fonte}``."""
    linhas = []
    for s in series.to_dict("records"):
        if s["metodologia"] not in FAMILIAS:
            raise ErroCadastro(f"Metodologia desconhecida em {s['serie_codigo']}: {s['metodologia']!r}")
        if s["fonte"] not in fontes:
            raise ErroCadastro(f"Fonte {s['fonte']!r} da série {s['serie_codigo']} não cadastrada")
        familia, ajuste = FAMILIAS[s["metodologia"]]
        # O CSV pode trazer "80.0" quando a coluna tem vazios (pandas grava como float).
        periodos = _texto(s.get("periodos_disponiveis"))
        linhas.append({
            "fonte_id": fontes[s["fonte"]], "fonte_original_id": fontes.get(_texto(s.get("fonte_original")) or ""),
            "codigo": s["serie_codigo"], "nome": _texto(s.get("serie_nome")) or s["serie_codigo"],
            "indicador": s["indicador"], "metodologia": s["metodologia"], "familia_metodologica": familia,
            "ajuste": ajuste, "escopo_territorial": s["escopo"],
            "periodicidade": _texto(s.get("periodicidade")) or "Mensal", "unidade": _texto(s.get("unidade")) or "Pessoa",
            "base_ipeadata": _texto(s.get("base_ipeadata")), "situacao_fonte": _texto(s.get("situacao_na_fonte")),
            "serie_atualizada_em": _instante(s.get("serie_atualizada_em")),
            "cobertura_inicio": _data(s.get("disponibilidade_inicio")), "cobertura_fim": _data(s.get("disponibilidade_fim")),
            "periodos_disponiveis": None if periodos is None else int(float(periodos)),
        })
    comando = insert(SerieIndicador)
    col = SerieIndicador.__table__.c
    identidade = ("fonte_id", "nome", "indicador", "metodologia", "escopo_territorial", "periodicidade", "unidade",
                  "base_ipeadata")
    mudou = tuple_(*[col[c] for c in identidade]).is_distinct_from(tuple_(*[comando.excluded[c] for c in identidade]))
    conexao.execute(
        comando.on_conflict_do_update(
            constraint="uq_series_indicadores_fonte_codigo",
            set_={
                **{c: comando.excluded[c] for c in linhas[0] if c not in ("fonte_id", "codigo")},
                # Se a identidade da série mudou, a comprovação anterior dos metadados deixa de valer.
                "status_procedencia": case((mudou, "nao_validado"), else_=col.status_procedencia),
                "procedencia_verificada_em": case((mudou, null()), else_=col.procedencia_verificada_em),
                "atualizado_em": func.now(),
            },
        ),
        linhas,
    )
    resultado = conexao.execute(
        select(SerieIndicador.codigo, SerieIndicador.id, SerieIndicador.indicador, SerieIndicador.metodologia, FonteDados.nome)
        .join(FonteDados, FonteDados.id == SerieIndicador.fonte_id)
    )
    return {c: {"id": i, "indicador": ind, "metodologia": m, "fonte": f} for c, i, ind, m, f in resultado}


def arquivos_ja_importados(conexao: Connection) -> set[tuple[str, str]]:
    return {(c, s) for c, s in conexao.execute(select(ArquivoImportado.caminho, ArquivoImportado.sha256))}


def registrar_arquivo(conexao: Connection, caminho: str, sha256: str, serie_id: int, linhas: int, importacao_id: int) -> None:
    comando = insert(ArquivoImportado).values(
        caminho=caminho, sha256=sha256, serie_id=serie_id, linhas=linhas, importacao_id=importacao_id
    )
    conexao.execute(comando.on_conflict_do_nothing(constraint="uq_arquivos_importados_caminho_sha256"))


def contagem_registros(conexao: Connection) -> dict[str, int]:
    return {codigo: total for codigo, total in conexao.execute(text(
        "SELECT s.codigo, count(r.id) FROM series_indicadores s "
        "LEFT JOIN registros_emprego r ON r.serie_id = s.id GROUP BY s.codigo ORDER BY s.codigo"
    ))}

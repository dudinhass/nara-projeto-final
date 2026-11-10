"""Verificação do banco: migração, objetos, integridade, desempenho e consultas de exemplo."""

from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from banco.conexao import verificar_conexao
from banco.consultas import METODOLOGIA_PADRAO, ConsultasEmprego, carregar_sql
from coleta.config import RAIZ_PROJETO

ALEMBIC_INI = RAIZ_PROJETO / "database" / "alembic.ini"
TABELAS = ("fontes_dados", "municipios", "series_indicadores", "registros_emprego", "revisoes_registros",
           "execucoes_importacao", "arquivos_importados", "inconsistencias_dados", "snapshots_origem",
           "auditorias_procedencia")


def revisao_head(ini: Path = ALEMBIC_INI) -> str | None:
    return ScriptDirectory.from_config(Config(str(ini))).get_current_head()


def _linhas(engine: Engine, sql: str, parametros: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with engine.connect() as con:
        return [dict(l) for l in con.execute(text(sql), parametros or {}).mappings()]


def _explain(engine: Engine, nome: str, sql: str, parametros: dict[str, Any]) -> dict[str, Any]:
    with engine.connect() as con:
        plano = [l[0] for l in con.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + sql), parametros)]
    tempo = next((float(m.group(1)) for l in plano if (m := re.search(r"Execution Time: ([\d.]+) ms", l))), None)
    nos = sorted({m.group(1) for l in plano for m in re.finditer(
        r"(Seq Scan|Index Only Scan|Bitmap Heap Scan|Bitmap Index Scan|Index Scan|Hash Join|Nested Loop|"
        r"Merge Join|HashAggregate|GroupAggregate)", l)})
    # "Index Scan using X" / "Index Only Scan using X" / "Bitmap Index Scan on X"
    indices = sorted({m.group(1) for l in plano if (m := re.search(r"(?:Scan using|Index Scan on) (\w+)", l))})
    sequenciais = sorted({m.group(1) for l in plano if (m := re.search(r"Seq Scan on (\w+)", l))})
    return {"consulta": nome, "tempo_execucao_ms": tempo, "operacoes": nos, "indices_usados": indices,
            "varreduras_sequenciais": sequenciais, "plano": plano}


def _ultimo_ano_completo(fim: date) -> int:
    return fim.year if fim.month == 12 else fim.year - 1


def verificar(engine: Engine, uf: str = "MA", cod_uf: str = "21") -> dict[str, Any]:
    inicio = time.monotonic()
    resultado: dict[str, Any] = {"conexao": verificar_conexao(engine, tentativas=2)}
    atual = _linhas(engine, "SELECT version_num FROM alembic_version")
    resultado["migracao"] = {"revisao_atual": atual[0]["version_num"] if atual else None, "revisao_head": revisao_head()}
    resultado["migracao"]["atualizada"] = resultado["migracao"]["revisao_atual"] == resultado["migracao"]["revisao_head"]

    resultado["tabelas"] = {t: _linhas(engine, f"SELECT count(*) AS n FROM {t}")[0]["n"] for t in TABELAS}
    resultado["tamanhos"] = _linhas(engine, """
        SELECT c.relname AS tabela, pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
               pg_size_pretty(pg_indexes_size(c.oid)) AS indices
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY pg_total_relation_size(c.oid) DESC""")
    resultado["restricoes"] = {l["tipo"]: l["n"] for l in _linhas(engine, """
        SELECT CASE contype WHEN 'p' THEN 'primary_key' WHEN 'f' THEN 'foreign_key' WHEN 'u' THEN 'unique'
                            WHEN 'c' THEN 'check' ELSE contype::text END AS tipo, count(*) AS n
        FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = 'public' GROUP BY 1""")}
    resultado["indices"] = _linhas(engine, "SELECT tablename AS tabela, indexname AS indice, indexdef AS definicao "
                                           "FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2")
    resultado["views"] = [l["viewname"] for l in _linhas(engine, "SELECT viewname FROM pg_views WHERE schemaname = 'public'")]

    resultado["integridade"] = {
        "chaves_naturais_duplicadas": _linhas(engine, """
            SELECT count(*) AS n FROM (SELECT 1 FROM registros_emprego
            GROUP BY serie_id, nivel_territorial, cod_territorio, data_referencia HAVING count(*) > 1) d""")[0]["n"],
        "municipios_cadastrados": _linhas(engine, "SELECT count(*) AS n FROM municipios WHERE uf = :uf", {"uf": uf})[0]["n"],
        "municipios_sem_observacao_por_serie": _linhas(engine, """
            SELECT s.codigo AS serie, count(*) FILTER (WHERE r.municipio_cod IS NULL) AS municipios_sem_observacao
            FROM series_indicadores s CROSS JOIN municipios m
            LEFT JOIN LATERAL (SELECT municipio_cod FROM registros_emprego r
                               WHERE r.serie_id = s.id AND r.municipio_cod = m.cod_ibge LIMIT 1) r ON true
            WHERE s.escopo_territorial = 'municipal' GROUP BY s.codigo ORDER BY 1"""),
        "series_sem_observacao": [l["codigo"] for l in _linhas(engine, """
            SELECT codigo FROM series_indicadores s
            WHERE NOT EXISTS (SELECT 1 FROM registros_emprego r WHERE r.serie_id = s.id)""")],
    }
    resultado["importacoes"] = _linhas(engine, """
        SELECT id, tipo, status, iniciado_em, finalizado_em, registros_lidos, registros_validos, registros_inseridos,
               registros_atualizados, registros_inalterados, registros_rejeitados, registros_ausentes_na_origem,
               arquivos_processados, arquivos_ignorados, mensagem_erro
        FROM execucoes_importacao ORDER BY id""")
    resultado["inconsistencias_por_tipo"] = {l["tipo"]: l["n"] for l in _linhas(
        engine, "SELECT tipo, count(*) AS n FROM inconsistencias_dados GROUP BY tipo ORDER BY tipo")}
    resultado["revisoes_registradas"] = resultado["tabelas"]["revisoes_registros"]

    contagem = lambda sql: {l["k"]: l["n"] for l in _linhas(engine, sql)}  # noqa: E731
    resultado["procedencia"] = {
        "registros": contagem("SELECT status_procedencia AS k, count(*) AS n FROM registros_emprego GROUP BY 1"),
        "series": contagem("SELECT status_procedencia AS k, count(*) AS n FROM series_indicadores GROUP BY 1"),
        "municipios": contagem("SELECT status_procedencia AS k, count(*) AS n FROM municipios GROUP BY 1"),
        "snapshots": contagem("SELECT status_procedencia AS k, count(*) AS n FROM snapshots_origem GROUP BY 1"),
        "fontes_autorizadas": [l["nome"] for l in _linhas(engine, "SELECT nome FROM fontes_dados WHERE autorizada_para_coleta")],
        "registros_sem_snapshot": _linhas(engine, "SELECT count(*) AS n FROM registros_emprego WHERE snapshot_id IS NULL")[0]["n"],
        "visiveis_nas_consultas": _linhas(engine, "SELECT count(*) AS n FROM vw_registros_validados")[0]["n"],
    }
    consultas = ConsultasEmprego(engine, uf, cod_uf)
    resultado["cobertura"] = consultas.cobertura_series()
    if resultado["procedencia"]["visiveis_nas_consultas"]:
        resultado["desempenho"], resultado["exemplos"] = _desempenho_e_exemplos(engine, consultas, uf, cod_uf)
    resultado["duracao_s"] = round(time.monotonic() - inicio, 2)
    return resultado


def _desempenho_e_exemplos(engine: Engine, c: ConsultasEmprego, uf: str, cod_uf: str) -> tuple[list, dict]:
    fim = c.ultima_competencia()
    ano = _ultimo_ano_completo(fim)
    periodo = {"inicio": date(ano, 1, 1), "fim": date(ano, 12, 1), "metodologia": METODOLOGIA_PADRAO}
    inicio_serie = c._cobertura_metodologia(METODOLOGIA_PADRAO, "municipal")[0]
    capital = _linhas(engine, "SELECT cod_ibge, nome FROM municipios WHERE capital AND uf = :uf", {"uf": uf})
    cod_capital = capital[0]["cod_ibge"] if capital else _linhas(engine, "SELECT min(cod_ibge) AS c FROM municipios")[0]["c"]
    serie_adm = _linhas(engine, "SELECT id FROM series_indicadores WHERE codigo = 'ADMISNC'")
    desempenho = [
        _explain(engine, f"ranking de municípios por saldo ({ano})",
                 carregar_sql("ranking_municipios").format(coluna="saldo", ordem="DESC"), {**periodo, "uf": uf, "limite": 10}),
        _explain(engine, "totais por município (todos, 1 ano)", carregar_sql("movimentacao_por_municipio"),
                 {**periodo, "uf": uf, "codigos": None}),
        _explain(engine, "evolução mensal da capital (histórico completo)", carregar_sql("evolucao_mensal"),
                 {"inicio": inicio_serie, "fim": fim, "metodologia": METODOLOGIA_PADRAO, "escopo": "municipal",
                  "nivel": "municipio", "cod_territorio": cod_capital}),
        _explain(engine, f"totais da UF ({ano})", carregar_sql("totais_uf"), {**periodo, "uf": uf, "cod_uf": cod_uf}),
    ]
    if serie_adm:
        desempenho.append(_explain(
            engine, "observações de um município numa série (tabela de fatos)",
            "SELECT data_referencia, valor FROM registros_emprego WHERE municipio_cod = :m AND serie_id = :s ORDER BY data_referencia",
            {"m": cod_capital, "s": serie_adm[0]["id"]}))
    exemplos = {
        "ultima_competencia": fim,
        "ano_de_referencia": ano,
        "ranking_saldo_maiores": c.ranking_municipios("saldo", periodo["inicio"], periodo["fim"], 10),
        "ranking_saldo_menores": c.ranking_municipios("saldo", periodo["inicio"], periodo["fim"], 5, "asc"),
        "ranking_admissoes": c.ranking_municipios("admissoes", periodo["inicio"], periodo["fim"], 5),
        "totais_uf": {k: v for k, v in c.totais_uf(periodo["inicio"], periodo["fim"]).items() if k != "mensal"},
        "indicadores_periodo": c.indicadores_periodo(periodo["inicio"], periodo["fim"]),
        "evolucao_anual_uf": c.evolucao_anual(None),
        "evolucao_anual_capital": c.evolucao_anual(cod_capital),
        "capital": cod_capital,
    }
    return desempenho, exemplos

"""Procedência dos dados no PostgreSQL: só o que foi comprovado no IpeaData alimenta as consultas.

A fonte simulada faz o papel do IpeaData. Cada teste cria uma situação em que algo não confere
(valor diferente, arquivo adulterado, fonte revogada, IpeaData fora do ar) e verifica que apenas
o que não passou na verificação sai das consultas, sem que nada seja apagado.
"""

from __future__ import annotations

import gzip
import json

import pytest
from alembic import command
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from banco.consultas import ConsultasEmprego, ErroConsulta
from banco.modelos import FonteDados, Municipio, SerieIndicador
from coleta.ipea_client import IpeaConnectionError
from tests.conftest import metadados
from tests.integration.auxiliares import PARTICAO_ADM, auditar, contar, importar, reescrever, todas_as_linhas, uma_linha
from tests.integration.conftest import configuracao_alembic

pytestmark = pytest.mark.postgresql

TOTAL = 31  # observações da coleta simulada: 14 (ADMISNC) + 14 (DESLIGNC) + 3 (CAGED12_ADMISN12)


def status(banco, serie: str | None = None) -> dict[str, int]:
    filtro = f"WHERE s.codigo = '{serie}'" if serie else ""
    return dict(todas_as_linhas(banco, "SELECT r.status_procedencia, count(*) FROM registros_emprego r "
                                       f"JOIN series_indicadores s ON s.id = r.serie_id {filtro} GROUP BY 1"))


def validados(banco) -> int:
    return contar(banco, "SELECT count(*) FROM vw_registros_validados")


def id_registro(banco, serie: str, territorio: str, data: str) -> int:
    return contar(banco, "SELECT r.id FROM registros_emprego r JOIN series_indicadores s ON s.id = r.serie_id "
                         "WHERE s.codigo = :s AND r.cod_territorio = :t AND r.data_referencia = :d",
                  s=serie, t=territorio, d=data)


@pytest.fixture
def importado(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    importar(banco, dirs)
    return banco


def valor_ao_vivo(estado_fonte, serie: str, territorio: str, data: str, novo: int | None) -> None:
    """Muda (ou remove, com ``None``) uma observação na resposta que o 'IpeaData' devolve agora."""
    registros = estado_fonte["paginas"][serie][0]
    for r in list(registros):
        if r["TERCODIGO"] == territorio and r["VALDATA"].startswith(data):
            if novo is None:
                registros.remove(r)
            else:
                r["VALVALOR"] = novo


# --- Nada nasce validado ------------------------------------------------------------------------

def test_importacao_nao_valida_nada_por_conta_propria(importado):
    assert status(importado) == {"nao_validado": TOTAL}
    assert validados(importado) == 0
    assert contar(importado, "SELECT count(*) FROM vw_municipios_validados") == 0
    assert contar(importado, "SELECT count(*) FROM vw_movimentacao_mensal") == 0
    with pytest.raises(ErroConsulta):  # a camada analítica não enxerga nada ainda
        ConsultasEmprego(importado).ranking_municipios("saldo")


def test_importacao_registra_origem_de_cada_observacao(importado):
    assert contar(importado, "SELECT count(*) FROM registros_emprego WHERE snapshot_id IS NULL") == 0
    sn = uma_linha(importado, "SELECT url, sha256, serie_codigo, coletado_em, arquivo_bruto FROM snapshots_origem "
                              "WHERE serie_codigo = 'ADMISNC'")
    assert sn["url"] == "https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')"
    assert len(sn["sha256"]) == 64 and sn["arquivo_bruto"].startswith("data/raw/ipeadata/ADMISNC/")
    assert contar(importado, "SELECT count(*) FROM snapshots_origem WHERE tipo = 'territorios'") == 1
    # cadastro de municípios agora referenciado ao IpeaData, com snapshot
    fonte = uma_linha(importado, "SELECT DISTINCT f.nome, f.autorizada_para_coleta FROM municipios m "
                                 "JOIN fontes_dados f ON f.id = m.fonte_referencia_id")
    assert fonte == {"nome": "IpeaData", "autorizada_para_coleta": True}
    assert contar(importado, "SELECT count(*) FROM municipios WHERE snapshot_id IS NULL") == 0
    assert contar(importado, "SELECT count(*) FROM fontes_dados WHERE autorizada_para_coleta") == 1


# --- Auditoria: validação contra o IpeaData ---------------------------------------------------------

def test_auditoria_valida_o_que_confere_com_o_ipeadata(importado, dirs, estado_fonte):
    r = auditar(importado, dirs, estado_fonte)
    assert r["status"] == "concluida"
    assert status(importado) == {"validado_ipeadata": TOTAL} and validados(importado) == TOTAL
    assert contar(importado, "SELECT count(*) FROM vw_municipios_validados") == 3
    assert dict(todas_as_linhas(importado, "SELECT codigo, status_procedencia FROM series_indicadores "
                                           "WHERE codigo IN ('ADMISNC','DESLIGNC','CAGED12_ADMISN12')")) == {
        "ADMISNC": "validado_ipeadata", "DESLIGNC": "validado_ipeadata", "CAGED12_ADMISN12": "validado_ipeadata"}
    assert contar(importado, "SELECT count(*) FROM snapshots_origem WHERE status_procedencia <> 'validado_ipeadata'") == 0
    adm = r["series"]["ADMISNC"]
    assert adm["resposta_oficial"]["registros_na_resposta"] == 23 and adm["banco_vs_resposta_oficial"]["iguais"] == 14
    assert all(a["situacao"] != "DIVERGENTE" for s in r["series"].values() for a in s["amostras"])
    assert uma_linha(importado, "SELECT status, resumo ->> 'territorios' AS t FROM auditorias_procedencia") == {
        "status": "concluida", "t": "concluida"}
    # as consultas voltam a funcionar, agora só com dados validados
    ranking = ConsultasEmprego(importado).ranking_municipios("saldo", limite=3)
    assert ranking[0]["municipio"] == "São Luís"


def test_evidencias_das_requisicoes_ficam_registradas(importado, dirs, estado_fonte):
    auditar(importado, dirs, estado_fonte)
    arquivo = json.loads((dirs.reports / "auditoria_procedencia.json").read_text(encoding="utf-8"))
    evidencias = arquivo["evidencias_http"]
    assert len(evidencias) == 2 + 3 * 2  # territórios (2) + metadados e valores de cada série
    assert all(e["url"].startswith("https://www.ipeadata.gov.br/api/odata4/") and e["status_http"] == 200
               and len(e["sha256"]) == 64 and e["consultado_em_utc"] for e in evidencias)
    assert any(e["rotulo"] == "ValoresSerie('ADMISNC')" for e in evidencias)


def test_valor_diferente_no_ipeadata_tira_so_aquele_registro(importado, dirs, estado_fonte):
    valor_ao_vivo(estado_fonte, "ADMISNC", "2111300", "2020-01", 7777)
    r = auditar(importado, dirs, estado_fonte)
    assert status(importado, "ADMISNC") == {"validado_ipeadata": 13, "nao_validado": 1}
    assert status(importado, "DESLIGNC") == {"validado_ipeadata": 14}
    assert contar(importado, "SELECT count(*) FROM registros_emprego") == TOTAL  # nada foi apagado
    assert validados(importado) == TOTAL - 1
    assert r["series"]["ADMISNC"]["motivos_nao_validado"] == {"ausente_ou_diferente_na_resposta_oficial_atual": 1}
    assert r["series"]["ADMISNC"]["banco_vs_resposta_oficial"]["valor_diferente"] == 1
    assert any(a["situacao"] == "DIVERGENTE" and a["valor_na_resposta_oficial"] == 7777 for a in r["series"]["ADMISNC"]["amostras"])


def test_registro_que_sumiu_do_ipeadata_nao_e_validado_nem_apagado(importado, dirs, estado_fonte):
    valor_ao_vivo(estado_fonte, "ADMISNC", "2103000", "2020-01", None)
    auditar(importado, dirs, estado_fonte)
    assert status(importado, "ADMISNC") == {"validado_ipeadata": 13, "nao_validado": 1}
    assert contar(importado, "SELECT count(*) FROM registros_emprego") == TOTAL


def test_arquivo_bruto_adulterado_invalida_a_origem(importado, dirs, estado_fonte):
    arquivo = uma_linha(importado, "SELECT arquivo_bruto FROM snapshots_origem WHERE serie_codigo = 'ADMISNC'")["arquivo_bruto"]
    (dirs.raiz / arquivo).write_bytes(gzip.compress(b'{"value": []}'))
    r = auditar(importado, dirs, estado_fonte)
    assert status(importado, "ADMISNC") == {"nao_validado": 14}
    assert status(importado, "DESLIGNC") == {"validado_ipeadata": 14}
    assert r["series"]["ADMISNC"]["motivos_nao_validado"] == {"origem_ou_metadados_nao_comprovados": 14}
    assert any("SHA-256" in p for s in r["series"]["ADMISNC"]["snapshots"] for p in s["problemas"])


def test_valor_alterado_no_banco_depois_da_coleta_e_detectado(importado, dirs, estado_fonte):
    rid = id_registro(importado, "ADMISNC", "2111300", "2020-02-01")
    with importado.begin() as con:
        con.execute(text("UPDATE registros_emprego SET valor = valor + 1 WHERE id = :i"), {"i": rid})
    r = auditar(importado, dirs, estado_fonte)
    assert contar(importado, "SELECT count(*) FROM registros_emprego WHERE id = :i AND status_procedencia = 'nao_validado'",
                  i=rid) == 1
    assert r["series"]["ADMISNC"]["motivos_nao_validado"] == {"diverge_do_arquivo_bruto": 1}
    assert validados(importado) == TOTAL - 1


def test_fonte_revogada_torna_os_registros_incompativeis_sem_apaga_los(importado, dirs, estado_fonte):
    with importado.begin() as con:
        con.execute(text("UPDATE fontes_dados SET autorizada_para_coleta = false WHERE nome = 'IpeaData'"))
    auditar(importado, dirs, estado_fonte)
    assert status(importado) == {"incompativel": TOTAL}
    assert validados(importado) == 0 and contar(importado, "SELECT count(*) FROM registros_emprego") == TOTAL
    assert contar(importado, "SELECT count(*) FROM series_indicadores WHERE status_procedencia = 'incompativel'") >= 3


def test_metadados_divergentes_invalidam_a_serie_inteira(importado, dirs, estado_fonte):
    estado_fonte["metadados"]["ADMISNC"] = metadados("ADMISNC", periodicidade="Anual")
    r = auditar(importado, dirs, estado_fonte)
    assert status(importado, "ADMISNC") == {"nao_validado": 14} and status(importado, "DESLIGNC") == {"validado_ipeadata": 14}
    assert r["series"]["ADMISNC"]["metadados"]["problemas"]


def test_municipio_com_dados_diferentes_no_cadastro_sai_das_consultas(importado, dirs, estado_fonte):
    for t in estado_fonte["territorios"]:
        if t["TERCODIGO"] == "2105302":
            t["TERNOME"] = "Imperatriz (renomeada)"
    r = auditar(importado, dirs, estado_fonte)
    assert contar(importado, "SELECT count(*) FROM vw_municipios_validados") == 2
    assert r["territorios"]["divergentes"] == ["2105302"] or "2105302" in str(r["territorios"])
    dele = contar(importado, "SELECT count(*) FROM registros_emprego WHERE municipio_cod = '2105302'")
    assert validados(importado) == TOTAL - dele  # as observações do município não aparecem nas views
    assert contar(importado, "SELECT count(*) FROM registros_emprego") == TOTAL


def test_ipeadata_fora_do_ar_deixa_auditoria_incompleta_sem_alterar_status(importado, dirs, estado_fonte):
    auditar(importado, dirs, estado_fonte)
    assert validados(importado) == TOTAL
    estado_fonte["falhas"]["meta:ADMISNC"] = IpeaConnectionError("fora do ar")
    r = auditar(importado, dirs, estado_fonte)
    assert r["status"] == "incompleta" and r["series"]["ADMISNC"]["situacao"] == "nao_concluida"
    assert validados(importado) == TOTAL  # sem resposta oficial, o status anterior permanece
    assert uma_linha(importado, "SELECT status FROM auditorias_procedencia WHERE id = (SELECT max(id) FROM auditorias_procedencia)") == {
        "status": "incompleta"}
    assert auditar(importado, dirs, estado_fonte)["status"] == "concluida"


def test_serie_nacional_nao_vira_dado_municipal(importado, dirs, estado_fonte):
    auditar(importado, dirs, estado_fonte)
    assert contar(importado, "SELECT count(*) FROM registros_emprego r JOIN series_indicadores s ON s.id = r.serie_id "
                             "WHERE s.escopo_territorial = 'nacional' AND (r.nivel_territorial <> 'brasil' OR r.municipio_cod IS NOT NULL)") == 0
    assert contar(importado, "SELECT count(*) FROM vw_movimentacao_mensal WHERE escopo_territorial = 'nacional' "
                             "AND nivel_territorial = 'municipio'") == 0


# --- Reimportação ----------------------------------------------------------------------------------

def test_reimportacao_preserva_validacao_e_revisao_a_revoga(importado, dirs, criar_pipeline, estado_fonte):
    auditar(importado, dirs, estado_fonte)
    importar(importado, dirs, "FULL")  # mesma carga de novo: nada muda, a validação permanece
    assert status(importado) == {"validado_ipeadata": TOTAL}

    reescrever(dirs, PARTICAO_ADM, lambda df: df.assign(valor=df["valor"].where(
        ~((df["cod_ibge"] == "2111300") & (df["data_referencia"] == "2020-01-01")), "555")))
    importar(importado, dirs, "FULL")
    assert status(importado) == {"validado_ipeadata": TOTAL - 1, "nao_validado": 1}  # só o revisado perde a validação
    assert validados(importado) == TOTAL - 1
    assert contar(importado, "SELECT count(*) FROM revisoes_registros") == 1


# --- Importador recusa origens não autorizadas ----------------------------------------------------------

def test_importador_ignora_arquivo_de_origem_nao_autorizada(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    manifesto = dirs.processed / "manifesto.json"
    dados = json.loads(manifesto.read_text(encoding="utf-8"))
    dados["arquivos"]["data/processed/admissoes/outra_fonte/X.csv"] = {
        "linhas": 1, "sha256": "0" * 64, "origem": "SERIE_DE_OUTRA_FONTE", "execucao_id": "x", "gravado_em": "x"}
    manifesto.write_text(json.dumps(dados), encoding="utf-8")
    resumo = importar(banco, dirs)
    assert {"arquivo": "data/processed/admissoes/outra_fonte/X.csv", "motivo": "origem_nao_autorizada"} in resumo.ignorados
    assert resumo.status == "concluida_com_rejeicoes" and resumo.totais["inseridos"] == TOTAL


@pytest.mark.parametrize("coluna, novo, motivo", [
    ("fonte", "Outro Portal", "fonte_nao_autorizada"),
    ("arquivo_bruto", "data/raw/outro_portal/x.json.gz", "origem_fora_do_ipeadata"),
])
def test_importador_rejeita_observacao_sem_origem_no_ipeadata(banco, criar_pipeline, dirs, coluna, novo, motivo):
    criar_pipeline().executar()
    reescrever(dirs, PARTICAO_ADM, lambda df: df.assign(**{coluna: [novo] + list(df[coluna][1:])}))
    resumo = importar(banco, dirs)
    assert resumo.totais["rejeitados"] == 1 and resumo.totais["inseridos"] == TOTAL - 1
    assert contar(banco, "SELECT count(*) FROM inconsistencias_dados WHERE tipo = :t", t=f"registro_rejeitado:{motivo}") == 1


# --- Garantias do banco ------------------------------------------------------------------------------

def test_banco_recusa_serie_de_fonte_nao_autorizada(importado):
    with pytest.raises(IntegrityError, match="nao autorizada"):
        with importado.begin() as con:
            fonte = con.execute(insert(FonteDados).values(
                nome="Outro Portal", papel="x", tipo_fonte="legado_nao_autorizado").returning(FonteDados.id)).scalar_one()
            con.execute(insert(SerieIndicador).values(
                fonte_id=fonte, codigo="X1", nome="x", indicador="admissoes", metodologia="m", familia_metodologica="novo_caged",
                escopo_territorial="municipal", periodicidade="Mensal", unidade="Pessoa"))


def test_banco_recusa_municipio_de_fonte_nao_autorizada(importado):
    with pytest.raises(IntegrityError, match="nao autorizada"):
        with importado.begin() as con:
            fonte = con.execute(insert(FonteDados).values(
                nome="Outro Portal", papel="x", tipo_fonte="legado_nao_autorizado").returning(FonteDados.id)).scalar_one()
            con.execute(insert(Municipio).values(cod_ibge="2100055", nome="x", uf="MA", cod_uf="21",
                                                 presente_ipeadata=True, fonte_referencia_id=fonte))


def test_banco_nao_deixa_fonte_que_nao_e_de_acesso_ficar_autorizada(importado):
    with pytest.raises(IntegrityError, match="autorizada_somente_se_acesso"):
        with importado.begin() as con:
            con.execute(text("UPDATE fontes_dados SET autorizada_para_coleta = true WHERE nome = 'MTE/Caged'"))


def test_banco_recusa_validado_sem_snapshot(importado):
    with pytest.raises(IntegrityError, match="validado_exige_snapshot"):
        with importado.begin() as con:
            con.execute(text("UPDATE registros_emprego SET snapshot_id = NULL, status_procedencia = 'validado_ipeadata', "
                             "procedencia_verificada_em = now() WHERE id = (SELECT min(id) FROM registros_emprego)"))
    with pytest.raises(IntegrityError, match="validado_exige_snapshot"):
        with importado.begin() as con:
            con.execute(text("UPDATE municipios SET snapshot_id = NULL, status_procedencia = 'validado_ipeadata', "
                             "procedencia_verificada_em = now() WHERE cod_ibge = '2111300'"))


def test_banco_recusa_snapshot_de_outra_serie(importado):
    with pytest.raises(IntegrityError, match="nao pertence a serie"):
        with importado.begin() as con:
            con.execute(text("UPDATE registros_emprego SET snapshot_id = (SELECT id FROM snapshots_origem WHERE serie_codigo = 'DESLIGNC') "
                             "WHERE id = :i"), {"i": id_registro(importado, "ADMISNC", "2111300", "2020-01-01")})


def test_banco_recusa_snapshot_com_url_fora_do_ipeadata(importado):
    with pytest.raises(IntegrityError, match="url_do_ipeadata"):
        with importado.begin() as con:
            con.execute(text("INSERT INTO snapshots_origem (tipo, serie_codigo, arquivo_bruto, arquivos, paginas, url, sha256, coletado_em) "
                             "VALUES ('serie', 'X', 'data/raw/x', '[]', 1, 'https://servicodados.ibge.gov.br/api/x', :sha, now())"),
                        {"sha": "a" * 64})


# --- A migração preserva o que já existe ------------------------------------------------------------------

def test_migracao_0002_preserva_dados_existentes(banco):  # 'banco' esvazia as tabelas antes
    with banco.begin() as con:
        cfg = configuracao_alembic(con)
        command.downgrade(cfg, "0001")
        con.execute(text("INSERT INTO fontes_dados (nome, papel) VALUES ('IpeaData','x'), ('MTE/Caged','x'), "
                         "('IBGE - API de localidades','x')"))
        con.execute(text("INSERT INTO municipios (cod_ibge, nome, uf, cod_uf, presente_ipeadata, fonte_referencia_id) "
                         "SELECT '2111300', 'São Luís', 'MA', '21', true, id FROM fontes_dados WHERE nome LIKE 'IBGE%'"))
        con.execute(text("INSERT INTO series_indicadores (fonte_id, codigo, nome, indicador, metodologia, familia_metodologica, ajuste, "
                         "escopo_territorial, periodicidade, unidade) SELECT id, 'ADMISNC', 'x', 'admissoes', 'Novo Caged - sem ajuste', "
                         "'novo_caged', 'sem_ajuste', 'municipal', 'Mensal', 'Pessoa' FROM fontes_dados WHERE nome = 'IpeaData'"))
        con.execute(text("INSERT INTO execucoes_importacao (tipo, status, fonte) VALUES ('FULL', 'concluida', 't')"))
        con.execute(text("INSERT INTO registros_emprego (serie_id, nivel_territorial, cod_territorio, municipio_cod, uf, data_referencia, "
                         "ano, mes, valor, arquivo_bruto, arquivo_processado, coletado_em, execucao_coleta_id, importacao_id, "
                         "atualizado_por_importacao_id) SELECT s.id, 'municipio', '2111300', '2111300', 'MA', '2020-01-01', 2020, 1, 123, "
                         "'raw', 'proc', now(), 'c', e.id, e.id FROM series_indicadores s, execucoes_importacao e"))
        antes_da_view = con.execute(text("SELECT count(*) FROM vw_movimentacao_mensal")).scalar_one()
        command.upgrade(cfg, "head")
        r = con.execute(text("SELECT valor, status_procedencia, snapshot_id FROM registros_emprego")).one()
        assert tuple(r) == (123, "nao_validado", None)  # dado preservado, mas ainda sem procedência comprovada
        assert con.execute(text("SELECT status_procedencia FROM municipios")).scalar_one() == "nao_validado"
        assert con.execute(text("SELECT status_procedencia FROM series_indicadores")).scalar_one() == "nao_validado"
        fontes = dict(con.execute(text("SELECT nome, tipo_fonte || ':' || autorizada_para_coleta FROM fontes_dados")).all())
        assert fontes == {"IpeaData": "acesso:true", "MTE/Caged": "origem_estatistica:false",
                          "IBGE - API de localidades": "legado_nao_autorizado:false"}
        assert antes_da_view == 1 and con.execute(text("SELECT count(*) FROM vw_movimentacao_mensal")).scalar_one() == 0
        command.downgrade(cfg, "0001")  # o caminho de volta também preserva os dados
        assert con.execute(text("SELECT valor FROM registros_emprego")).scalar_one() == 123
        assert con.execute(text("SELECT count(*) FROM vw_movimentacao_mensal")).scalar_one() == 1
        command.upgrade(cfg, "head")

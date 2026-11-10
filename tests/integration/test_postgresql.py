"""Testes contra o PostgreSQL de testes (pulados se o servidor não estiver disponível).

Os arquivos de entrada são gerados pelo pipeline da etapa 1 com a fonte
simulada de ``tests/conftest.py`` (3 municípios sintéticos, 3 meses), e um
teste final importa os arquivos processados reais (cópia em pasta temporária).
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timezone

import pytest
from alembic import command
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from banco.conexao import verificar_conexao
from banco.consultas import ConsultasEmprego, ErroConsulta
from banco.importacao import TRAVA_IMPORTACAO, ErroImportacao, Importador
from banco.modelos import FonteDados, Municipio, RegistroEmprego, SerieIndicador
from banco.reconciliacao import reconciliar
from coleta.config import RAIZ_PROJETO, Diretorios
from tests.conftest import M, nova_atualizacao, valor
from tests.integration.conftest import configuracao_alembic

pytestmark = pytest.mark.postgresql


from tests.integration.auxiliares import (  # noqa: E402
    PARTICAO_ADM, auditar, contar, importar, reescrever, todas_as_linhas, uma_linha,
)


# --- Infraestrutura ---------------------------------------------------------------

def test_conexao_e_configuracao_do_servidor(banco):
    info = verificar_conexao(banco, tentativas=1)
    assert info["versao"].startswith("PostgreSQL 17")
    assert info["banco"].endswith("_test")
    assert info["timezone"] == "UTC"


def test_migracoes_do_zero_reaplicacao_e_conferencia_com_modelos(engine_testes):
    with engine_testes.begin() as con:
        cfg = configuracao_alembic(con)
        command.downgrade(cfg, "base")
        assert con.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                                "AND tablename <> 'alembic_version'")).scalar_one() == 0
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")  # reaplicar não faz nada nem falha
        command.check(cfg)  # levanta exceção se modelos e banco divergirem
        tabelas = {r[0] for r in con.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
        assert {"municipios", "fontes_dados", "series_indicadores", "registros_emprego", "execucoes_importacao",
                "inconsistencias_dados", "revisoes_registros", "arquivos_importados"} <= tabelas
        assert con.execute(text("SELECT count(*) FROM pg_views WHERE viewname='vw_movimentacao_mensal'")).scalar_one() == 1
        indices = {r[0] for r in con.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='registros_emprego'"))}
        assert {"uq_registros_emprego_chave_natural", "ix_registros_emprego_municipio_serie_data",
                "ix_registros_emprego_serie_nivel_data"} <= indices


# --- Restrições do esquema ----------------------------------------------------------

@pytest.fixture
def cadastro_minimo(banco):
    with banco.begin() as con:
        fonte = con.execute(insert(FonteDados).values(
            nome="IpeaData", papel="teste", tipo_fonte="acesso", autorizada_para_coleta=True).returning(FonteDados.id)).scalar_one()
        con.execute(insert(Municipio).values(cod_ibge="2111300", nome="São Luís", uf="MA", cod_uf="21",
                                             presente_ipeadata=True, fonte_referencia_id=fonte))
        serie = con.execute(insert(SerieIndicador).values(
            fonte_id=fonte, codigo="ADMISNC", nome="x", indicador="admissoes", metodologia="Novo Caged - sem ajuste",
            familia_metodologica="novo_caged", ajuste="sem_ajuste", escopo_territorial="municipal",
            periodicidade="Mensal", unidade="Pessoa").returning(SerieIndicador.id)).scalar_one()
        imp = con.execute(text("INSERT INTO execucoes_importacao (tipo, status, fonte) VALUES ('FULL','em_andamento','t') "
                               "RETURNING id")).scalar_one()
    return {"fonte": fonte, "serie": serie, "imp": imp}


def registro(c, **mudancas):
    base = dict(serie_id=c["serie"], nivel_territorial="municipio", cod_territorio="2111300", municipio_cod="2111300",
                uf="MA", data_referencia=date(2020, 1, 1), ano=2020, mes=1, valor=10, arquivo_bruto="raw",
                arquivo_processado="proc", coletado_em=datetime.now(timezone.utc), execucao_coleta_id="col",
                importacao_id=c["imp"], atualizado_por_importacao_id=c["imp"])
    return {**base, **mudancas}


def test_insercao_valida_e_relacionamentos(banco, cadastro_minimo):
    with banco.begin() as con:
        con.execute(insert(RegistroEmprego).values(**registro(cadastro_minimo)))
    with banco.connect() as con:
        linha = con.execute(text(
            "SELECT m.nome, s.codigo, f.nome FROM registros_emprego r JOIN municipios m ON m.cod_ibge = r.municipio_cod "
            "JOIN series_indicadores s ON s.id = r.serie_id JOIN fontes_dados f ON f.id = s.fonte_id")).one()
    assert tuple(linha) == ("São Luís", "ADMISNC", "IpeaData")


@pytest.mark.parametrize(
    "mudancas, restricao",
    [
        ({"municipio_cod": "2199999", "cod_territorio": "2199999"}, "fk_registros_emprego_municipio_cod_municipios"),
        ({"serie_id": 9999}, "fk_registros_emprego_serie_id_series_indicadores"),
        ({"nivel_territorial": "estado", "cod_territorio": "21"}, "municipio_coerente_com_nivel"),
        ({"nivel_territorial": "brasil", "cod_territorio": "0", "municipio_cod": None}, "cod_territorio_coerente_com_nivel"),
        ({"data_referencia": date(2020, 1, 15)}, "data_primeiro_dia_do_periodo"),
        ({"ano": 2021}, "ano_coerente"),
        ({"nivel_territorial": "regiao"}, "violates check constraint"),  # viola mais de uma; o PG relata uma
        ({"valor": None}, "valor"),  # NOT NULL: ausência nunca vira linha
    ],
)
def test_restricoes_rejeitam_registros_invalidos(banco, cadastro_minimo, mudancas, restricao):
    with pytest.raises(IntegrityError, match=restricao):
        with banco.begin() as con:
            con.execute(insert(RegistroEmprego).values(**registro(cadastro_minimo, **mudancas)))


def test_chave_natural_impede_duplicata(banco, cadastro_minimo):
    with banco.begin() as con:
        con.execute(insert(RegistroEmprego).values(**registro(cadastro_minimo)))
    with pytest.raises(IntegrityError, match="uq_registros_emprego_chave_natural"):
        with banco.begin() as con:
            con.execute(insert(RegistroEmprego).values(**registro(cadastro_minimo, valor=99)))


@pytest.mark.parametrize("codigo, cod_uf", [("123", "12"), ("2211001", "21"), ("21113OO", "21")])
def test_codigos_ibge_invalidos_sao_rejeitados(banco, cadastro_minimo, codigo, cod_uf):
    with pytest.raises(IntegrityError, match="ck_municipios"):
        with banco.begin() as con:
            con.execute(insert(Municipio).values(cod_ibge=codigo, nome="x", uf="MA", cod_uf=cod_uf,
                                                 presente_ipeadata=True, fonte_referencia_id=cadastro_minimo["fonte"]))


# --- Importação ----------------------------------------------------------------------

def test_importacao_full_carrega_toda_a_base(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    resumo = importar(banco, dirs)
    assert resumo.status == "concluida"
    t = resumo.totais
    assert t["lidos"] == t["validos"] == t["inseridos"] == 31  # 14 + 14 + 3 observações da coleta simulada
    assert t["rejeitados"] == t["atualizados"] == 0
    assert contar(banco, "SELECT count(*) FROM municipios") == 3
    assert contar(banco, "SELECT count(*) FROM series_indicadores") == 11
    assert contar(banco, "SELECT count(*) FROM registros_emprego WHERE nivel_territorial = 'municipio'") == 16
    assert contar(banco, "SELECT count(*) FROM arquivos_importados") == 5
    linha = uma_linha(banco,
        "SELECT r.arquivo_bruto, r.execucao_coleta_id, r.importacao_id, e.status FROM registros_emprego r "
        "JOIN execucoes_importacao e ON e.id = r.importacao_id LIMIT 1")
    assert linha["arquivo_bruto"].startswith("data/raw/ipeadata/") and linha["execucao_coleta_id"].startswith("full-")
    assert linha["status"] == "concluida"


def test_importacao_e_idempotente(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    importar(banco, dirs)
    segunda = importar(banco, dirs, "FULL")
    assert (segunda.totais["inseridos"], segunda.totais["atualizados"], segunda.totais["inalterados"]) == (0, 0, 31)
    incremental = importar(banco, dirs, "INCREMENTAL")
    assert incremental.totais["arquivos_processados"] == 0 and incremental.totais["arquivos_ignorados"] == 5
    assert contar(banco, "SELECT count(*) FROM registros_emprego") == 31


def test_incremental_aplica_revisao_preservando_historico(banco, criar_pipeline, dirs, estado_fonte):
    criar_pipeline().executar()
    importar(banco, dirs)
    registros = estado_fonte["paginas"]["ADMISNC"][0]
    for r in registros:
        if r["TERCODIGO"] == "2111300" and r["VALDATA"].startswith("2020-03"):
            r["VALVALOR"] = 555
    registros.append(valor("ADMISNC", "2020-04-01", 321, M, "2111300"))
    nova_atualizacao(estado_fonte, "ADMISNC")
    criar_pipeline("incremental").executar()

    resumo = importar(banco, dirs, "INCREMENTAL")
    assert resumo.totais["inseridos"] == 1 and resumo.totais["atualizados"] == 1 and resumo.totais["revisoes"] == 1
    revisao = uma_linha(banco,
        "SELECT v.valor_anterior, v.valor_novo, v.importacao_id, r.valor, r.importacao_id AS criado_por, "
        "r.atualizado_por_importacao_id FROM revisoes_registros v JOIN registros_emprego r ON r.id = v.registro_id"
    )
    assert (revisao["valor_anterior"], revisao["valor_novo"], revisao["valor"]) == (102, 555, 555)
    assert revisao["criado_por"] == 1 and revisao["atualizado_por_importacao_id"] == resumo.importacao_id
    # Linhas não revisadas mantêm a importação que as criou.
    assert contar(banco, "SELECT count(*) FROM registros_emprego WHERE atualizado_por_importacao_id <> importacao_id") == 1
    assert importar(banco, dirs, "INCREMENTAL").totais["arquivos_processados"] == 0


def test_falha_desfaz_o_arquivo_em_curso_e_retomada_completa(banco, criar_pipeline, dirs, monkeypatch):
    criar_pipeline().executar()
    original, chamadas = Importador._registrar_ausentes, {"n": 0}

    def falhar_no_segundo(self, *args, **kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            raise RuntimeError("falha simulada no meio do arquivo")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Importador, "_registrar_ausentes", falhar_no_segundo)
    with pytest.raises(RuntimeError, match="falha simulada"):
        importar(banco, dirs, "INCREMENTAL")
    status, mensagem = todas_as_linhas(banco, "SELECT status, mensagem_erro FROM execucoes_importacao")[0]
    assert status == "falhou" and "falha simulada" in mensagem
    assert contar(banco, "SELECT count(*) FROM arquivos_importados") == 1  # só o primeiro arquivo confirmou
    parcial = contar(banco, "SELECT count(*) FROM registros_emprego")
    assert parcial == contar(banco, "SELECT linhas FROM arquivos_importados")  # nada do segundo arquivo ficou

    monkeypatch.undo()
    resumo = importar(banco, dirs, "INCREMENTAL")
    assert resumo.totais["arquivos_ignorados"] == 1 and resumo.status == "concluida"
    assert contar(banco, "SELECT count(*) FROM registros_emprego") == 31


def test_registros_invalidos_sao_rejeitados_e_registrados(banco, criar_pipeline, dirs):
    criar_pipeline().executar()

    def estragar(df):
        df.loc[0, "cod_ibge"] = df.loc[0, "cod_territorio_original"] = "2199999"  # fora do cadastro
        df.loc[1, "valor"] = ""                                                    # ausente: não vira zero
        df.loc[2, "valor"] = "-5"                                                  # contagem negativa
        return df

    reescrever(dirs, PARTICAO_ADM, estragar)
    resumo = importar(banco, dirs)
    assert resumo.status == "concluida_com_rejeicoes" and resumo.totais["rejeitados"] == 3
    tipos = dict(todas_as_linhas(banco, "SELECT tipo, count(*) FROM inconsistencias_dados GROUP BY tipo"))
    assert tipos == {"registro_rejeitado:municipio_fora_do_cadastro": 1, "registro_rejeitado:valor_ausente": 1,
                     "registro_rejeitado:valor_negativo_em_contagem": 1}
    assert contar(banco, "SELECT count(*) FROM registros_emprego") == 28


def test_arquivo_alterado_sem_nova_coleta_nao_e_importado(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    caminho = dirs.raiz / PARTICAO_ADM
    caminho.write_text(caminho.read_text(encoding="utf-8").replace(",101,", ",999,"), encoding="utf-8")
    resumo = importar(banco, dirs)
    assert {"arquivo": PARTICAO_ADM, "motivo": "arquivo_alterado_apos_coleta"} in resumo.ignorados
    assert resumo.status == "concluida_com_rejeicoes"
    assert contar(banco, "SELECT count(*) FROM registros_emprego WHERE valor = 999") == 0


def test_observacao_que_sumiu_da_origem_e_registrada_e_mantida(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    importar(banco, dirs)
    reescrever(dirs, PARTICAO_ADM, lambda df: df.iloc[1:])
    resumo = importar(banco, dirs, "FULL")
    assert resumo.totais["ausentes_na_origem"] == 1
    assert contar(banco, "SELECT count(*) FROM registros_emprego") == 31
    assert contar(banco, "SELECT count(*) FROM inconsistencias_dados WHERE tipo = 'ausente_na_origem'") == 1


def test_pre_condicoes_impedem_importacao(banco, criar_pipeline, dirs, estado_fonte):
    estado_fonte["falhas"]["DESLIGNC"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        criar_pipeline().executar()
    with pytest.raises(ErroImportacao, match="em andamento"):
        importar(banco, dirs)


def test_trava_impede_importacoes_simultaneas(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    with banco.connect() as outra:
        outra.execute(text("SELECT pg_advisory_lock(:t)"), {"t": TRAVA_IMPORTACAO})
        with pytest.raises(ErroImportacao, match="Outra importação"):
            importar(banco, dirs)
        outra.execute(text("SELECT pg_advisory_unlock(:t)"), {"t": TRAVA_IMPORTACAO})


# --- Consultas e reconciliação ----------------------------------------------------------

def test_consultas_saldo_lacunas_e_metodologia(banco, criar_pipeline, dirs, estado_fonte):
    criar_pipeline().executar()
    importar(banco, dirs)
    assert auditar(banco, dirs, estado_fonte)["status"] == "concluida"
    c = ConsultasEmprego(banco)
    assert c.ultima_competencia() == date(2020, 3, 1)
    caxias = {l["data_referencia"]: l for l in c.evolucao_mensal("2103000")}
    assert caxias[date(2020, 2, 1)]["situacao"] == "sem_observacao" and caxias[date(2020, 2, 1)]["saldo"] is None
    assert caxias[date(2020, 1, 1)]["saldo"] == 5 - 5
    sao_luis = {l["data_referencia"]: l for l in c.evolucao_mensal("2111300")}
    assert sao_luis[date(2020, 1, 1)]["saldo"] == 100 - 80
    ranking = c.ranking_municipios("saldo", limite=3)
    assert ranking[0]["municipio"] == "São Luís" and ranking[0]["saldo"] == (100 + 101 + 102) - (80 + 81 + 82)
    totais = c.totais_uf()
    assert totais["admissoes_uf"] == 1000 + 1001 + 1002  # total oficial da UF, diferente da soma sintética
    assert totais["admissoes_soma_municipios"] == sum(l["admissoes"] or 0 for l in c.movimentacao_por_municipio())
    anual = c.evolucao_anual("2111300")
    assert anual[0]["ano_completo"] is False and anual[0]["meses_com_saldo"] == 3
    with pytest.raises(ErroConsulta, match="não tem admissões e desligamentos"):
        c.ranking_municipios(metodologia="CAGED tradicional")
    with pytest.raises(ErroConsulta, match="Indicador inválido"):
        c.ranking_municipios("valor; DROP TABLE municipios")
    with pytest.raises(ErroConsulta, match="não cadastrados"):
        c.evolucao_mensal("2199999")


def test_reconciliacao_concilia_e_detecta_divergencia(banco, criar_pipeline, dirs):
    criar_pipeline().executar()
    importar(banco, dirs)
    assert reconciliar(banco, dirs)["situacao"] == "conciliado"
    with banco.begin() as con:
        con.execute(text("UPDATE registros_emprego SET valor = valor + 1 WHERE id = (SELECT min(id) FROM registros_emprego)"))
    resultado = reconciliar(banco, dirs)
    assert resultado["situacao"] == "divergente" and resultado["totais"]["grupos_divergentes"] == 1
    assert resultado["divergencias"][0]["valores_diferentes"] == 1


# --- Base real ---------------------------------------------------------------------------

def test_importacao_da_base_real_completa_e_reconciliada(banco, tmp_path):
    """Importa uma cópia dos arquivos processados reais (só leitura) no banco de testes."""
    real = Diretorios(RAIZ_PROJETO)
    if not (real.processed / "manifesto.json").exists():
        pytest.skip("Base real não coletada")
    copia = Diretorios(tmp_path)
    shutil.copytree(real.processed, copia.processed)
    copia.checkpoints.mkdir(parents=True)
    shutil.copy(real.checkpoints / "estado.json", copia.checkpoints / "estado.json")
    if (real.reports / "validacao.json").exists():
        copia.reports.mkdir(parents=True)
        shutil.copy(real.reports / "validacao.json", copia.reports / "validacao.json")

    resumo = Importador(banco, copia, "FULL", total_municipios=217).executar()
    assert resumo.status == "concluida" and resumo.totais["rejeitados"] == 0
    assert contar(banco, "SELECT count(*) FROM municipios WHERE uf = 'MA'") == 217
    resultado = reconciliar(banco, copia)
    assert resultado["situacao"] == "conciliado", resultado["divergencias"]
    assert resultado["totais"]["linhas_banco"] == resumo.totais["inseridos"] == resumo.totais["lidos"]

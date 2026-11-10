"""Pipeline de ponta a ponta com uma fonte simulada (FakeCliente)."""

from __future__ import annotations

import gzip
import hashlib
import json

import pandas as pd
import pytest

from coleta import esquema
from coleta.armazenamento import ler_json
from coleta.checkpoint import Checkpoint, ErroCheckpoint
from coleta.config import SERIES
from coleta.ipea_client import IpeaConnectionError
from coleta.repositorio import RepositorioDados
from coleta.territorios import ErroTerritorial
from tests.conftest import M, nova_atualizacao, valor

ADM = SERIES["ADMISNC"]


def chaves_valores(df: pd.DataFrame) -> list[tuple]:
    colunas = list(esquema.CHAVE_OBSERVACAO) + ["valor"]
    return sorted(df[colunas].astype(str).itertuples(index=False, name=None))


# --- FULL --------------------------------------------------------------------------

def test_full_gera_base_completa_e_rastreavel(criar_pipeline, dirs, estado_fonte):
    resumo = criar_pipeline().executar()
    assert resumo["status"] == "concluida"
    assert all(t["status"] == "concluida" for t in resumo["tarefas"].values())

    repo = RepositorioDados(dirs)
    base = repo.ler(ADM)
    municipais = base[base["nivel_territorial"] == "municipio"]
    assert sorted(municipais["cod_ibge"].unique()) == ["2103000", "2105302", "2111300"]  # Piauí excluído
    assert len(municipais) == 8  # 3 × 3 meses menos a lacuna de Caxias em fevereiro
    assert set(base[base["nivel_territorial"] != "municipio"]["cod_territorio_original"]) == {"21", "0"}
    assert (repo.dir_particoes(ADM) / "ano=2020.csv").exists()
    assert repo.arquivo_agregados(ADM).exists()
    assert repo.arquivo_nacional(SERIES["CAGED12_ADMISN12"]).exists()

    # Origem: o bruto referenciado existe e o hash confere com o metadado de download
    bruto = dirs.raiz / municipais["arquivo_bruto"].iloc[0]
    meta = json.loads(bruto.with_name(bruto.name.replace(".json.gz", ".meta.json")).read_text("utf-8"))
    assert hashlib.sha256(gzip.decompress(bruto.read_bytes())).hexdigest() == meta["sha256"]

    painel = esquema.ler_csv(dirs.consolidado / "painel_municipal_mensal.csv", esquema.PAINEL)
    assert len(painel) == 9
    caxias_fev = painel[(painel["cod_ibge"] == "2103000") & (painel["data_referencia"] == "2020-02-01")].iloc[0]
    assert caxias_fev["status_admissoes"] == "observacao_ausente" and pd.isna(caxias_fev["saldo"])
    imperatriz_mar = painel[(painel["cod_ibge"] == "2105302") & (painel["data_referencia"] == "2020-03-01")].iloc[0]
    assert imperatriz_mar["status_admissoes"] == "zero_encontrado"

    anual = pd.read_csv(dirs.reports / "cobertura_municipio_ano_indicador.csv", dtype={"codigo_ibge": str})
    assert {"codigo_ibge", "municipio", "ano", "indicador", "fonte", "meses_esperados", "meses_encontrados",
            "status_cobertura"} <= set(anual.columns)
    caxias = anual[(anual["codigo_ibge"] == "2103000") & (anual["indicador"] == "admissoes")].iloc[0]
    assert (caxias["meses_esperados"], caxias["meses_encontrados"], caxias["status_cobertura"]) == (3, 2, "incompleto")
    assert (dirs.consolidado / "series.csv").exists() and (dirs.consolidado / "execucoes.csv").exists()
    assert RepositorioDados(dirs).verificar_manifesto()["sha256_divergente"] == []


def test_full_e_idempotente(criar_pipeline, dirs):
    criar_pipeline().executar()
    primeira = chaves_valores(RepositorioDados(dirs).ler(ADM))
    resumo = criar_pipeline().executar()
    segunda = RepositorioDados(dirs).ler(ADM)
    assert chaves_valores(segunda) == primeira
    assert not segunda.duplicated(subset=list(esquema.CHAVE_OBSERVACAO)).any()
    assert resumo["tarefas"]["serie:ADMISNC"]["diferencas"] == {
        "novas": 0, "revisadas_na_janela": 0, "revisadas_fora_janela": 0, "ausentes_na_fonte": 0}
    assert not (dirs.reports / "alteracoes").exists()


def test_paginacao_completa_no_pipeline(criar_pipeline, dirs, estado_fonte):
    paginas = estado_fonte["paginas"]["ADMISNC"][0]
    estado_fonte["paginas"]["ADMISNC"] = [paginas[:10], paginas[10:20], paginas[20:]]
    criar_pipeline().executar()
    assert estado_fonte["downloads"].count("ADMISNC") == 3
    snapshot = Checkpoint(dirs.checkpoints).tarefa("serie:ADMISNC")["ultima_conclusao"]["snapshot"]
    assert snapshot["paginas"] == 3
    estat = Checkpoint(dirs.checkpoints).tarefa("serie:ADMISNC")["ultima_conclusao"]["resultado"]["estatisticas"]
    assert estat["registros_lidos"] == len(paginas)
    assert len(RepositorioDados(dirs).ler(ADM)) == 8 + 3 + 3  # municípios + UF + Brasil


def test_duplicatas_da_fonte_sao_tratadas(criar_pipeline, dirs, estado_fonte):
    registros = estado_fonte["paginas"]["ADMISNC"][0]
    registros.append(dict(registros[0]))                                   # repetição exata
    registros.append(valor("ADMISNC", "2020-01-01", 77, M, "2105302"))     # conflito
    resumo = criar_pipeline().executar()
    tarefa = resumo["tarefas"]["serie:ADMISNC"]
    assert tarefa["duplicatas_exatas_removidas"] == 1 and tarefa["chaves_conflitantes"] == 1
    rejeitados = pd.read_csv(next((dirs.reports / "rejeitados").glob("*_ADMISNC.csv")))
    assert (rejeitados["motivo"] == "chave_duplicada_conflitante").sum() == 2
    base = RepositorioDados(dirs).ler(ADM)
    assert not base.duplicated(subset=list(esquema.CHAVE_OBSERVACAO)).any()


def test_concorrencia_maior_que_um(criar_pipeline, dirs, estado_fonte):
    resumo = criar_pipeline(max_concorrencia=3).executar()
    assert resumo["status"] == "concluida"
    assert sorted(estado_fonte["downloads"]) == sorted(["Territorios", "ADMISNC", "DESLIGNC", "CAGED12_ADMISN12"])


# --- Falhas, checkpoint e retomada -----------------------------------------------------------

def test_retomada_apos_interrupcao_nao_refaz_o_concluido(criar_pipeline, dirs, estado_fonte):
    estado_fonte["falhas"]["DESLIGNC"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        criar_pipeline().executar()
    checkpoint = Checkpoint(dirs.checkpoints)
    assert checkpoint.execucao is not None  # continua "em andamento"
    assert checkpoint.tarefa("serie:DESLIGNC")["status"] != "concluida"

    resumo = criar_pipeline().executar()
    assert resumo["retomada"] is True and resumo["status"] == "concluida"
    assert estado_fonte["downloads"].count("ADMISNC") == 1  # baixado e processado antes da interrupção
    assert estado_fonte["downloads"].count("DESLIGNC") == 1
    assert estado_fonte["downloads"].count("Territorios") == 1


def test_retomada_reaproveita_download_ja_validado(criar_pipeline, dirs, estado_fonte, monkeypatch):
    import coleta.pipeline as modulo

    original = modulo.processar
    chamadas = {"n": 0}

    def interromper_uma_vez(lotes, ctx):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise KeyboardInterrupt
        return original(lotes, ctx)

    monkeypatch.setattr(modulo, "processar", interromper_uma_vez)
    with pytest.raises(KeyboardInterrupt):
        criar_pipeline().executar()
    assert Checkpoint(dirs.checkpoints).tarefa("serie:ADMISNC")["etapa"] == "baixada"

    criar_pipeline().executar()
    assert estado_fonte["downloads"].count("ADMISNC") == 1  # não baixou de novo


def test_bruto_alterado_nao_e_reaproveitado(criar_pipeline, dirs, estado_fonte, monkeypatch):
    import coleta.pipeline as modulo

    monkeypatch.setattr(modulo, "processar", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        criar_pipeline().executar()
    arquivo = dirs.raiz / Checkpoint(dirs.checkpoints).tarefa("serie:ADMISNC")["download"]["arquivos"][0]
    arquivo.write_bytes(gzip.compress(b'{"value": []}'))  # adulterado
    monkeypatch.undo()
    criar_pipeline().executar()
    assert estado_fonte["downloads"].count("ADMISNC") == 2


def test_falha_transitoria_marca_tarefa_e_proxima_execucao_retoma(criar_pipeline, dirs, estado_fonte):
    estado_fonte["falhas"]["DESLIGNC"] = IpeaConnectionError("rede caiu")
    resumo = criar_pipeline().executar()
    assert resumo["status"] == "incompleta"
    assert resumo["tarefas"]["serie:DESLIGNC"]["status"] == "falhou"
    assert "rede caiu" in resumo["tarefas"]["serie:DESLIGNC"]["erro"]
    assert resumo["tarefas"]["serie:ADMISNC"]["status"] == "concluida"
    historico = Checkpoint(dirs.checkpoints).historico()
    assert historico[-1]["status"] == "incompleta" and "serie:DESLIGNC" in historico[-1]["pendentes"]

    resumo = criar_pipeline().executar()
    assert resumo["status"] == "concluida" and resumo["retomada"] is True
    assert estado_fonte["downloads"].count("ADMISNC") == 1
    assert estado_fonte["downloads"].count("DESLIGNC") == 1


def test_modo_diferente_nao_atropela_execucao_interrompida(criar_pipeline, estado_fonte):
    estado_fonte["falhas"]["DESLIGNC"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        criar_pipeline("full").executar()
    with pytest.raises(ErroCheckpoint, match="interrompida"):
        criar_pipeline("incremental").executar()
    assert criar_pipeline("incremental", reiniciar=True).executar()["status"] == "concluida"


def test_arquivos_incompletos_sao_removidos(criar_pipeline, dirs):
    sobras = [dirs.processed / "x.csv.tmp", dirs.raw_ipeadata / "ADMISNC" / "a.json.gz.part"]
    sem_meta = dirs.raw_ipeadata / "ADMISNC" / "orfao.json.gz"
    for caminho in [*sobras, sem_meta]:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"x")
    resumo = criar_pipeline().executar()
    assert len(resumo["arquivos_incompletos_removidos"]) == 3
    assert not any(c.exists() for c in [*sobras, sem_meta])


def test_serie_inexistente_falha_sem_derrubar_as_demais(criar_pipeline, estado_fonte):
    del estado_fonte["metadados"]["CAGED12_ADMISN12"]
    resumo = criar_pipeline().executar()
    assert resumo["tarefas"]["serie:CAGED12_ADMISN12"]["status"] == "falhou"
    assert resumo["tarefas"]["consolidacao"]["status"] == "concluida"


# --- Política territorial -----------------------------------------------------------------

def test_politica_estrita_interrompe_se_cadastro_do_ipeadata_incompleto(criar_pipeline, estado_fonte, dirs):
    estado_fonte["territorios"].pop()  # cadastro do IpeaData com 2 municípios, esperados 3
    with pytest.raises(ErroTerritorial, match="esperado 3"):
        criar_pipeline(total_municipios_esperado=3).executar()
    assert Checkpoint(dirs.checkpoints).tarefa("territorios")["status"] == "falhou"
    assert estado_fonte["downloads"] == ["Territorios"]  # nenhuma série foi baixada


def test_politica_alerta_segue_e_registra(criar_pipeline, estado_fonte, dirs):
    estado_fonte["territorios"].pop()
    resumo = criar_pipeline(politica_territorial="alerta", total_municipios_esperado=3).executar()
    assert resumo["status"] == "concluida"
    problemas = Checkpoint(dirs.checkpoints).tarefa("territorios")["ultima_conclusao"]["resultado"]["problemas"]
    assert problemas and "esperado 3" in problemas[0]


# --- INCREMENTAL ------------------------------------------------------------------------

def test_incremental_sem_base_faz_carga_completa(criar_pipeline, dirs):
    resumo = criar_pipeline("incremental").executar()
    assert resumo["status"] == "concluida"
    assert len(RepositorioDados(dirs).ler(ADM)) == 14


def test_incremental_pula_series_sem_atualizacao_na_fonte(criar_pipeline, estado_fonte):
    criar_pipeline("full").executar()
    estado_fonte["downloads"].clear()
    resumo = criar_pipeline("incremental").executar()
    assert resumo["tarefas"]["serie:ADMISNC"]["situacao"] == "sem_alteracoes_na_fonte"
    assert estado_fonte["downloads"] == ["Territorios"]


def test_incremental_aplica_novos_meses_e_revisoes_na_janela(criar_pipeline, dirs, estado_fonte):
    criar_pipeline("full").executar()
    registros = estado_fonte["paginas"]["ADMISNC"][0]
    for r in registros:
        if r["TERCODIGO"] == "2111300" and r["VALDATA"].startswith("2020-03"):
            r["VALVALOR"] = 555                       # revisão na janela (mar-abr)
        if r["TERCODIGO"] == "2111300" and r["VALDATA"].startswith("2020-01"):
            r["VALVALOR"] = 444                       # revisão fora da janela
    registros.append(valor("ADMISNC", "2020-04-01", 321, M, "2111300"))  # mês novo
    registros.append(valor("ADMISNC", "2020-04-01", 9, M, "2211001"))    # outra UF, ignorado
    nova_atualizacao(estado_fonte, "ADMISNC")

    resumo = criar_pipeline("incremental").executar()
    assert resumo["tarefas"]["serie:ADMISNC"]["diferencas"] == {
        "novas": 1, "revisadas_na_janela": 1, "revisadas_fora_janela": 1, "ausentes_na_fonte": 0}
    sao_luis = RepositorioDados(dirs).ler(ADM).query("cod_ibge == '2111300'")
    valores = dict(zip(sao_luis["data_referencia"].dt.strftime("%Y-%m"), sao_luis["valor"]))
    assert valores == {"2020-01": 100, "2020-02": 101, "2020-03": 555, "2020-04": 321}

    log = pd.read_csv(next((dirs.reports / "alteracoes").glob("incremental-*_ADMISNC.csv")))
    fora = log[log["tipo"] == "revisada_fora_janela"].iloc[0]
    assert not fora["aplicada"] and fora["valor_anterior"] == 100 and fora["valor_novo"] == 444
    assert resumo["tarefas"]["serie:DESLIGNC"]["situacao"] == "sem_alteracoes_na_fonte"


def test_incremental_e_idempotente(criar_pipeline, dirs, estado_fonte):
    criar_pipeline("full").executar()
    estado_fonte["paginas"]["ADMISNC"][0].append(valor("ADMISNC", "2020-04-01", 321, M, "2111300"))
    nova_atualizacao(estado_fonte, "ADMISNC")
    criar_pipeline("incremental").executar()
    manifesto = ler_json(dirs.processed / "manifesto.json")
    base = chaves_valores(RepositorioDados(dirs).ler(ADM))

    resumo = criar_pipeline("incremental", forcar=True).executar()  # baixa de novo mesmo sem mudança
    assert resumo["tarefas"]["serie:ADMISNC"]["diferencas"] == {
        "novas": 0, "revisadas_na_janela": 0, "revisadas_fora_janela": 0, "ausentes_na_fonte": 0}
    assert chaves_valores(RepositorioDados(dirs).ler(ADM)) == base
    particao = "data/processed/admissoes/ipeadata/ADMISNC/ano=2020.csv"
    assert ler_json(dirs.processed / "manifesto.json")["arquivos"][particao] == manifesto["arquivos"][particao]


def test_incremental_mantem_observacao_que_sumiu_da_fonte(criar_pipeline, dirs, estado_fonte):
    criar_pipeline("full").executar()
    registros = estado_fonte["paginas"]["ADMISNC"][0]
    registros[:] = [r for r in registros if not (r["TERCODIGO"] == "2103000" and r["VALDATA"].startswith("2020-03"))]
    nova_atualizacao(estado_fonte, "ADMISNC")
    resumo = criar_pipeline("incremental").executar()
    assert resumo["tarefas"]["serie:ADMISNC"]["diferencas"]["ausentes_na_fonte"] == 1
    base = RepositorioDados(dirs).ler(ADM)
    assert ((base["cod_ibge"] == "2103000") & (base["data_referencia"] == "2020-03-01")).any()


def test_interrupcao_por_excecao_fica_registrada_no_historico(criar_pipeline, dirs, estado_fonte):
    estado_fonte["falhas"]["DESLIGNC"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        criar_pipeline().executar()
    ultima = Checkpoint(dirs.checkpoints).historico()[-1]
    assert ultima["status"] == "interrompida" and "KeyboardInterrupt" in ultima["erro"]
    resumo = criar_pipeline().executar()
    assert Checkpoint(dirs.checkpoints).historico()[-1]["retomadas"] == 1 and resumo["status"] == "concluida"

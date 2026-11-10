from __future__ import annotations

import pytest

from coleta import territorios
from coleta.checkpoint import Checkpoint
from coleta.investigacao import buscar_series, perfil_valores, situacao_serie
from coleta.relatorios import GeradorRelatorios
from coleta.validacao import validar_base, verificar_territorios
from tests.conftest import SERIES_TESTE, M, valor


# --- Cadastro de municípios (somente IpeaData) -------------------------------------------------

def registro(codigo, nome="Município", nivel="Municípios"):
    return {"NIVNOME": nivel, "TERCODIGO": codigo, "TERNOME": nome, "TERCAPITAL": False, "TERAREA": 10.0}


def test_cadastro_valido_do_ipeadata():
    registros = [registro("2111300", "São Luís"), registro("2105302", "Imperatriz")]
    municipios, problemas = territorios.validar_cadastro(registros, "21", 2, "estrita")
    assert municipios == {"2111300": "São Luís", "2105302": "Imperatriz"} and problemas == []
    df = territorios.municipios_dataframe(registros, municipios, "MA", "21")
    assert df["presente_ipeadata"].all() and df["municipio"].tolist() == ["Imperatriz", "São Luís"]


@pytest.mark.parametrize(
    "registros, esperado",
    [
        ([registro("211130")], "inválido"),                       # 6 dígitos
        ([registro("2211001")], "inválido"),                      # outra UF
        ([registro("2111300", "")], "sem nome"),
        ([registro("2111300"), registro("2111300")], "repetido"),
        ([registro("21", nivel="Estados")], "nível"),
        ([registro("2111300")], "esperado 217"),                  # total diferente do esperado
    ],
)
def test_politica_estrita_interrompe_cadastro_invalido(registros, esperado):
    with pytest.raises(territorios.ErroTerritorial, match=esperado):
        territorios.validar_cadastro(registros, "21", 217, "estrita")


def test_politica_alerta_registra_e_segue():
    municipios, problemas = territorios.validar_cadastro([registro("2111300"), registro("2211001")], "21", None, "alerta")
    assert list(municipios) == ["2111300"] and len(problemas) == 1


@pytest.mark.parametrize("codigo, valido", [("2111300", True), ("211130", False), ("2211001", False), ("21113OO", False)])
def test_codigo_municipal_valido(codigo, valido):
    assert territorios.codigo_municipal_valido(codigo, "21") is valido


# --- Validação da base persistida -------------------------------------------------------------

def test_validacao_aprova_base_gerada_pelo_pipeline(criar_pipeline, dirs):
    criar_pipeline().executar()
    relatorio = validar_base(dirs, Checkpoint(dirs.checkpoints).estado, "21", SERIES_TESTE)
    assert relatorio["situacao"] == "aprovada", relatorio["problemas_criticos"]
    consist = relatorio["consistencia"]["ADMISNC"]["soma_municipios_vs_total_uf"]
    assert consist["meses_comparados"] == 3  # dados sintéticos: soma ≠ UF, registrado como diferença
    assert relatorio["painel"]["linhas"] == relatorio["painel"]["linhas_esperadas"] == 9


def test_validacao_detecta_arquivo_adulterado(criar_pipeline, dirs):
    criar_pipeline().executar()
    particao = dirs.processed / "admissoes" / "ipeadata" / "ADMISNC" / "ano=2020.csv"
    particao.write_text(particao.read_text(encoding="utf-8").replace(",101,", ",999,"), encoding="utf-8")
    relatorio = validar_base(dirs, Checkpoint(dirs.checkpoints).estado, "21", SERIES_TESTE)
    assert relatorio["situacao"] == "reprovada"
    assert relatorio["integridade_arquivos"]["sha256_divergente"] == ["data/processed/admissoes/ipeadata/ADMISNC/ano=2020.csv"]


def test_validacao_detecta_bruto_removido(criar_pipeline, dirs):
    criar_pipeline().executar()
    for bruto in (dirs.raw_ipeadata / "ADMISNC").glob("*.json.gz"):
        bruto.unlink()
    relatorio = validar_base(dirs, Checkpoint(dirs.checkpoints).estado, "21", SERIES_TESTE)
    assert any("rastreabilidade" in p for p in relatorio["problemas_criticos"])


def test_verificar_territorios_aponta_outra_uf():
    import pandas as pd

    obs = pd.DataFrame({"nivel_territorial": ["municipio", "municipio", "estado"],
                        "cod_ibge": pd.array(["2111300", "2211001", "21"], dtype="string")})
    resultado = verificar_territorios(obs, {"2111300"}, "21")
    assert resultado["registros_de_outra_uf"] == 1
    assert resultado["codigos_fora_do_cadastro_ipeadata"] == ["2211001"]


# --- Relatórios ------------------------------------------------------------------------------

def test_relatorios_usam_numeros_reais_da_execucao(criar_pipeline, dirs):
    criar_pipeline().executar()
    from coleta.armazenamento import salvar_json

    salvar_json(validar_base(dirs, Checkpoint(dirs.checkpoints).estado, "21", SERIES_TESTE), dirs.reports / "validacao.json")
    destinos = GeradorRelatorios(dirs).gerar()
    cobertura = destinos["cobertura_historica"].read_text(encoding="utf-8")
    assert "| ADMISNC | 23 | 14 | 0 | 0 | 0 | 14 |" in cobertura  # 3 meses × 8 registros − 1 lacuna
    assert "2103000 | Caxias | 2020-02" in cobertura                # lacuna listada
    assert "Nenhuma pendência de coleta" in cobertura
    validacao = destinos["relatorio_validacao"].read_text(encoding="utf-8")
    assert "Resultado: **APROVADA**" in validacao
    assert "Sem resultado registrado" in validacao  # pytest.xml ausente: não inventa


def test_relatorio_sem_dados_nao_inventa(dirs):
    assert "Sem dados" in GeradorRelatorios(dirs).cobertura_historica()


# --- Investigação ------------------------------------------------------------------------

def test_buscar_series_por_nome_codigo_e_fonte_sem_falsos_positivos():
    catalogo = [
        {"SERCODIGO": "ADMISNC", "SERNOME": "Empregados - admissões - Novo Caged", "FNTSIGLA": "MTE/Caged"},
        {"SERCODIGO": "X1", "SERNOME": "Empregados - demissões", "FNTSIGLA": "Outra"},
        {"SERCODIGO": "Y", "SERNOME": "Algo sem relação no nome", "FNTSIGLA": "Min. Economia/SEPRT/Novo Caged"},
        {"SERCODIGO": "ADH_X_RUR", "SERNOME": "Ocupados - áreas rurais", "FNTSIGLA": "IPEA"},  # "rais" em "rurais"
        {"SERCODIGO": "MIN", "SERNOME": "Produtos de minerais", "FNTSIGLA": "IBGE"},
    ]
    assert [m["SERCODIGO"] for m in buscar_series(catalogo)] == ["ADMISNC", "X1", "Y"]


def test_perfil_aponta_adequacao_municipal():
    municipal = perfil_valores(iter([valor("S", "2020-01-01", 1, M, "2111300"), valor("S", "2020-01-01", 2, "Brasil", "0")]))
    nacional = perfil_valores(iter([valor("S", "2020-01-01", 1, "", "")]))
    assert municipal["adequada_para_analise_municipal"] is True
    assert nacional["adequada_para_analise_municipal"] is False
    assert municipal["municipios_teste_presentes"]["2111300"] is True


@pytest.mark.parametrize(
    "meta, esperado",
    [({"SERSTATUS": "A", "SERNOME": "x"}, "ativa"), ({"SERSTATUS": "I", "SERNOME": "x"}, "inativa"),
     ({"SERSTATUS": None, "SERNOME": "Empregados - INATIVA"}, "inativa"), ({"SERSTATUS": None, "SERNOME": "x"}, "não informado")],
)
def test_situacao_serie(meta, esperado):
    assert situacao_serie(meta) == esperado

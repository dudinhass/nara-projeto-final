"""Esquema dos arquivos processados: colunas, tipos e chaves naturais.

É a fonte única usada para gravar, reler e documentar os dados
(``docs/modelo_dados.md`` descreve as mesmas definições). Os tipos
PostgreSQL são uma proposta para a etapa 2; nenhuma tabela é criada aqui.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo_pandas: str
    tipo_postgres: str
    descricao: str
    anulavel: bool = False


OBSERVACAO = (
    Coluna("fonte", "string", "text", "Fonte de acesso (IpeaData)"),
    Coluna("fonte_original", "string", "text", "Fonte primária informada nos metadados (FNTSIGLA)"),
    Coluna("serie_codigo", "string", "text", "Código da série no IpeaData (SERCODIGO)"),
    Coluna("serie_nome", "string", "text", "Nome da série (SERNOME)"),
    Coluna("indicador", "string", "text", "admissoes | desligamentos | saldo"),
    Coluna("metodologia", "string", "text", "CAGED tradicional | Novo Caged - sem ajuste | Novo Caged - com ajuste"),
    Coluna("periodicidade", "string", "text", "Periodicidade (PERNOME), ex.: Mensal"),
    Coluna("unidade", "string", "text", "Unidade (UNINOME), ex.: Pessoa"),
    Coluna("nivel_territorial", "string", "text", "municipio | estado | brasil"),
    Coluna("nivel_territorial_original", "string", "text", "NIVNOME como veio da API (vazio em séries nacionais)", True),
    Coluna("cod_territorio_original", "string", "text", "TERCODIGO como veio da API (vazio em séries nacionais)", True),
    Coluna("cod_ibge", "string", "varchar(7)", "Código IBGE: 7 dígitos (município) ou 2 (UF); vazio para Brasil", True),
    Coluna("territorio_nome", "string", "text", "Nome do município publicado no IpeaData, sigla da UF ou 'Brasil'"),
    Coluna("uf", "string", "char(2)", "Sigla da UF; vazio para Brasil", True),
    Coluna("data_referencia", "datetime64[ns]", "date", "Primeiro dia do período de referência"),
    Coluna("ano", "Int64", "smallint", "Ano de referência"),
    Coluna("mes", "Int64", "smallint", "Mês de referência (séries mensais)", True),
    Coluna("valor", "Int64", "integer", "Valor publicado; nunca preenchido quando ausente"),
    Coluna("serie_atualizada_em", "string", "timestamptz", "SERATUALIZACAO dos metadados no momento da coleta", True),
    Coluna("coletado_em_utc", "string", "timestamptz", "Momento do download da resposta bruta"),
    Coluna("execucao_id", "string", "text", "Execução de coleta que gravou o valor"),
    Coluna("arquivo_bruto", "string", "text", "Resposta original preservada em data/raw"),
)

# Identifica unicamente uma observação. ``serie_codigo`` já distingue
# indicador e metodologia; nível e código territorial impedem colisão
# entre o município, a UF e o Brasil num mesmo mês.
CHAVE_OBSERVACAO = ("fonte", "serie_codigo", "nivel_territorial", "cod_territorio_original", "data_referencia")

PAINEL = (
    Coluna("cod_ibge", "string", "char(7)", "Código municipal de 7 dígitos (publicado no IpeaData)"),
    Coluna("municipio", "string", "text", "Nome publicado no IpeaData"),
    Coluna("uf", "string", "char(2)", "Sigla da UF"),
    Coluna("data_referencia", "datetime64[ns]", "date", "Mês de referência"),
    Coluna("ano", "Int64", "smallint", "Ano"),
    Coluna("mes", "Int64", "smallint", "Mês"),
    Coluna("admissoes", "Int64", "integer", "Admissões (vazio se não publicado)", True),
    Coluna("desligamentos", "Int64", "integer", "Desligamentos (vazio se não publicado)", True),
    Coluna("saldo", "Int64", "integer", "admissoes - desligamentos, só quando ambos existem", True),
    Coluna("status_admissoes", "string", "text", "Situação da observação (ver STATUS_OBSERVACAO)"),
    Coluna("status_desligamentos", "string", "text", "Situação da observação (ver STATUS_OBSERVACAO)"),
    Coluna("serie_admissoes", "string", "text", "Série de origem das admissões"),
    Coluna("serie_desligamentos", "string", "text", "Série de origem dos desligamentos"),
    Coluna("metodologia", "string", "text", "Metodologia comum às duas séries"),
    Coluna("fonte", "string", "text", "Fonte de acesso"),
)
CHAVE_PAINEL = ("cod_ibge", "data_referencia")

MUNICIPIO = (
    Coluna("cod_ibge", "string", "char(7)", "Código municipal de 7 dígitos (IpeaData, Territorios)"),
    Coluna("municipio", "string", "text", "Nome publicado no IpeaData"),
    Coluna("uf", "string", "char(2)", "Sigla da UF"),
    Coluna("cod_uf", "string", "char(2)", "Código da UF (2 primeiros dígitos do código municipal)"),
    Coluna("nome_ipeadata", "string", "text", "Nome no cadastro de territórios do IpeaData", True),
    Coluna("capital", "boolean", "boolean", "Capital da UF (IpeaData)", True),
    Coluna("area_km2", "Float64", "numeric(12,2)", "Área em km² (IpeaData)", True),
    Coluna("presente_ipeadata", "boolean", "boolean", "Consta no cadastro de territórios do IpeaData"),
)
CHAVE_MUNICIPIO = ("cod_ibge",)

STATUS_OBSERVACAO = {
    "valor_encontrado": "Observação publicada com valor maior que zero",
    "zero_encontrado": "Observação publicada com valor zero",
    "observacao_ausente": "Período coberto pela série, mas sem registro para o território",
    "nao_disponibilizado_pela_fonte": "Período fora da disponibilidade da série",
    "falha_coleta": "A coleta falhou e não há dados válidos para verificar",
}


def dtypes(colunas: tuple[Coluna, ...]) -> dict[str, str]:
    return {c.nome: c.tipo_pandas for c in colunas if not c.tipo_pandas.startswith("datetime")}


def nomes(colunas: tuple[Coluna, ...]) -> list[str]:
    return [c.nome for c in colunas]


def colunas_data(colunas: tuple[Coluna, ...]) -> list[str]:
    return [c.nome for c in colunas if c.tipo_pandas.startswith("datetime")]


def conformar(df: pd.DataFrame, colunas: tuple[Coluna, ...]) -> pd.DataFrame:
    """Reordena e tipa as colunas conforme o esquema (falha se faltar alguma).

    Texto ausente vira string vazia ("não se aplica"), para que as chaves
    nunca contenham nulos; números ausentes ficam ``<NA>``.
    """
    faltantes = [nome for nome in nomes(colunas) if nome not in df.columns]
    if faltantes:
        raise ValueError(f"Colunas ausentes: {faltantes}")
    df = df[nomes(colunas)].copy()
    for coluna in colunas_data(colunas):
        df[coluna] = pd.to_datetime(df[coluna])
    df = df.astype(dtypes(colunas))
    for coluna in colunas:
        if coluna.tipo_pandas == "string":
            df[coluna.nome] = df[coluna.nome].fillna("")
    return df


def _opcoes_leitura(colunas: tuple[Coluna, ...]) -> dict:
    return {
        "dtype": {nome: ("string" if tipo == "boolean" else tipo) for nome, tipo in dtypes(colunas).items()},
        "parse_dates": colunas_data(colunas),
        "keep_default_na": False,
        "na_values": {c.nome: [""] for c in colunas if c.tipo_pandas != "string"},
    }


def _finalizar_leitura(df: pd.DataFrame, colunas: tuple[Coluna, ...]) -> pd.DataFrame:
    for coluna in colunas:
        if coluna.tipo_pandas == "boolean":
            df[coluna.nome] = df[coluna.nome].map({"True": True, "False": False}).astype("boolean")
    return conformar(df, colunas)


def ler_csv(caminho: Path, colunas: tuple[Coluna, ...]) -> pd.DataFrame:
    return _finalizar_leitura(pd.read_csv(caminho, **_opcoes_leitura(colunas)), colunas)


def ler_csv_em_lotes(caminho: Path, colunas: tuple[Coluna, ...], tamanho: int) -> Iterator[pd.DataFrame]:
    """Mesmo resultado de ``ler_csv``, em blocos de ``tamanho`` linhas (memória limitada)."""
    with pd.read_csv(caminho, chunksize=tamanho, **_opcoes_leitura(colunas)) as leitor:
        for bloco in leitor:
            yield _finalizar_leitura(bloco, colunas)

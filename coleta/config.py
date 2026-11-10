"""Configuração centralizada da coleta.

Tudo que varia por ambiente (URL, timeouts, tentativas, modo, lotes,
concorrência, janela incremental, política territorial) é lido de variáveis
de ambiente ou do arquivo ``.env`` (veja ``.env.example``). Constantes de
domínio (séries, níveis territoriais) ficam aqui para não se espalharem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_PROJETO / ".env")

MODOS = ("full", "incremental")
POLITICAS_TERRITORIAIS = ("estrita", "alerta")

# Sigla -> código de 2 dígitos da UF. Constante de configuração (não é dado importado); a auditoria
# confere o código da UF contra o nível Estados do IpeaData (Territorios).
CODIGOS_UF = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}


def _env(nome: str, padrao: str) -> str:
    valor = os.getenv(nome)
    return valor.strip() if valor and valor.strip() else padrao


def _env_int(nome: str, padrao: int) -> int:
    return int(_env(nome, str(padrao)))


def _env_float(nome: str, padrao: float) -> float:
    return float(_env(nome, str(padrao)))


def _env_bool(nome: str, padrao: bool) -> bool:
    return _env(nome, "1" if padrao else "0").lower() in {"1", "true", "sim", "yes"}


# --- API do IpeaData -----------------------------------------------------------

@dataclass(frozen=True)
class ConfigAPI:
    """Parâmetros de acesso à API OData v4 do IpeaData."""

    base_url: str = "https://www.ipeadata.gov.br/api/odata4/"
    timeout_conexao: float = 10.0
    # As séries municipais completas têm ~64 MB e levam 30-45 s para chegar.
    timeout_leitura: float = 180.0
    max_tentativas_extras: int = 3
    backoff_segundos: float = 2.0
    backoff_maximo_segundos: float = 300.0
    # Intervalo mínimo entre o início de duas requisições (limite de taxa).
    intervalo_minimo_segundos: float = 1.0
    max_paginas: int = 1000
    user_agent: str = "emprego-maranhao/0.4 (projeto academico; python-requests)"
    # Regra do projeto: dados SÓ do IpeaData. O cliente recusa qualquer outro host, inclusive em
    # links de paginação e redirecionamentos. Não é configurável por variável de ambiente.
    hosts_autorizados: tuple[str, ...] = ("www.ipeadata.gov.br",)


def carregar_config_api() -> ConfigAPI:
    padrao = ConfigAPI()
    return ConfigAPI(
        base_url=_env("IPEA_BASE_URL", padrao.base_url),
        timeout_conexao=_env_float("IPEA_TIMEOUT_CONEXAO", padrao.timeout_conexao),
        timeout_leitura=_env_float("IPEA_TIMEOUT_LEITURA", padrao.timeout_leitura),
        max_tentativas_extras=_env_int("IPEA_MAX_TENTATIVAS", padrao.max_tentativas_extras),
        backoff_segundos=_env_float("IPEA_BACKOFF_SEGUNDOS", padrao.backoff_segundos),
        backoff_maximo_segundos=_env_float("IPEA_BACKOFF_MAXIMO_SEGUNDOS", padrao.backoff_maximo_segundos),
        intervalo_minimo_segundos=_env_float("IPEA_INTERVALO_MINIMO_SEGUNDOS", padrao.intervalo_minimo_segundos),
    )


# --- Coleta --------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigColeta:
    """Comportamento do pipeline de coleta."""

    modo: str = "full"
    uf_sigla: str = "MA"
    tamanho_lote: int = 50_000
    max_concorrencia: int = 1
    janela_incremental_meses: int = 12
    aplicar_revisoes_fora_janela: bool = False
    politica_territorial: str = "estrita"
    # Total de municípios esperado no cadastro do IpeaData (constante do projeto); None desativa.
    total_municipios_esperado: int | None = None

    def __post_init__(self) -> None:
        if self.modo not in MODOS:
            raise ValueError(f"COLETA_MODO inválido: {self.modo!r} (use {MODOS})")
        if self.uf_sigla not in CODIGOS_UF:
            raise ValueError(f"UF_INTERESSE inválida: {self.uf_sigla!r}")
        if self.politica_territorial not in POLITICAS_TERRITORIAIS:
            raise ValueError(f"VALIDACAO_TERRITORIAL inválida: {self.politica_territorial!r}")
        if self.tamanho_lote < 1 or self.max_concorrencia < 1 or self.janela_incremental_meses < 1:
            raise ValueError("Lote, concorrência e janela incremental devem ser >= 1")

    @property
    def codigo_uf(self) -> str:
        return CODIGOS_UF[self.uf_sigla]


def carregar_config_coleta(**sobrescritas: object) -> ConfigColeta:
    padrao = ConfigColeta()
    valores = dict(
        modo=_env("COLETA_MODO", padrao.modo).lower(),
        uf_sigla=_env("UF_INTERESSE", padrao.uf_sigla).upper(),
        tamanho_lote=_env_int("COLETA_TAMANHO_LOTE", padrao.tamanho_lote),
        max_concorrencia=_env_int("COLETA_MAX_CONCORRENCIA", padrao.max_concorrencia),
        janela_incremental_meses=_env_int("INCREMENTAL_JANELA_MESES", padrao.janela_incremental_meses),
        aplicar_revisoes_fora_janela=_env_bool(
            "INCREMENTAL_APLICAR_REVISOES_FORA_JANELA", padrao.aplicar_revisoes_fora_janela
        ),
        politica_territorial=_env("VALIDACAO_TERRITORIAL", padrao.politica_territorial).lower(),
    )
    uf = str(valores["uf_sigla"])
    esperado = os.getenv("TOTAL_MUNICIPIOS_ESPERADO")
    valores["total_municipios_esperado"] = (
        int(esperado) if esperado else TOTAL_MUNICIPIOS_UF.get(uf)
    )
    valores.update({chave: valor for chave, valor in sobrescritas.items() if valor is not None})
    return ConfigColeta(**valores)  # type: ignore[arg-type]


NIVEL_LOG = _env("LOG_LEVEL", "INFO")

# Quantidade de municípios esperada por UF, usada só para conferir o cadastro do IpeaData.
TOTAL_MUNICIPIOS_UF = {"MA": 217}


# --- Diretórios ----------------------------------------------------------------

@dataclass(frozen=True)
class Diretorios:
    """Layout de dados. Testes usam uma raiz temporária."""

    raiz: Path = RAIZ_PROJETO

    @property
    def dados(self) -> Path:
        return self.raiz / "data"

    @property
    def raw_ipeadata(self) -> Path:
        return self.dados / "raw" / "ipeadata"

    @property
    def processed(self) -> Path:
        return self.dados / "processed"

    @property
    def consolidado(self) -> Path:
        return self.processed / "consolidado"

    @property
    def checkpoints(self) -> Path:
        return self.dados / "checkpoints"

    @property
    def reports(self) -> Path:
        return self.dados / "reports"

    @property
    def logs(self) -> Path:
        return self.raiz / "logs"

    @property
    def docs(self) -> Path:
        return self.raiz / "docs"


DIRETORIOS = Diretorios()


# --- PostgreSQL ----------------------------------------------------------------

@dataclass(frozen=True)
class ConfigBanco:
    """Conexão com o PostgreSQL. A senha vem só do ambiente (.env não versionado)."""

    host: str = "localhost"
    porta: int = 5432
    usuario: str = "emprego"
    senha: str = ""
    banco: str = "emprego_maranhao"
    banco_testes: str = "emprego_maranhao_test"
    url: str | None = None
    url_testes: str | None = None
    timeout_conexao: int = 10
    tamanho_lote: int = 5_000

    def _montar(self, banco: str) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+psycopg", username=self.usuario, password=self.senha or None,
            host=self.host, port=self.porta, database=banco,
        ).render_as_string(hide_password=False)

    @property
    def url_principal(self) -> str:
        return self.url or self._montar(self.banco)

    @property
    def url_banco_testes(self) -> str:
        return self.url_testes or self._montar(self.banco_testes)


def carregar_config_banco() -> ConfigBanco:
    padrao = ConfigBanco()
    return ConfigBanco(
        host=_env("POSTGRES_HOST", padrao.host),
        porta=_env_int("POSTGRES_PORT", padrao.porta),
        usuario=_env("POSTGRES_USER", padrao.usuario),
        senha=os.getenv("POSTGRES_PASSWORD", ""),
        banco=_env("POSTGRES_DB", padrao.banco),
        banco_testes=_env("POSTGRES_TEST_DB", padrao.banco_testes),
        url=os.getenv("DATABASE_URL") or None,
        url_testes=os.getenv("TEST_DATABASE_URL") or None,
        timeout_conexao=_env_int("POSTGRES_TIMEOUT_CONEXAO", padrao.timeout_conexao),
        tamanho_lote=_env_int("IMPORTACAO_TAMANHO_LOTE", padrao.tamanho_lote),
    )


# --- Fontes ------------------------------------------------------------------------
# Regra obrigatória: todos os dados vêm do IpeaData. A fonte estatística original (MTE/Caged) é só
# um atributo descritivo informado pelo próprio IpeaData; nunca é acessada.
FONTE_IPEADATA = "IpeaData"
FONTE_ORIGINAL_MTE = "MTE/Caged"
URL_IPEADATA = "https://www.ipeadata.gov.br/api/odata4/"
HOSTS_AUTORIZADOS = ("www.ipeadata.gov.br",)


# --- Séries ----------------------------------------------------------------------

@dataclass(frozen=True)
class SerieConfig:
    """Série coletada e como ela deve ser interpretada.

    ``escopo`` = "municipal": a série tem nível Municípios e alimenta o painel.
    ``escopo`` = "nacional": só total Brasil; usada como referência, nunca
    convertida em dado municipal.
    """

    codigo: str
    indicador: str
    metodologia: str
    escopo: str
    # Base do IpeaData esperada nos metadados (Regional / Macroeconômico); None = não conferir.
    base_ipeadata: str | None = None


SERIES_MUNICIPAIS = (
    SerieConfig("ADMISNC", "admissoes", "Novo Caged - sem ajuste", "municipal", "Regional"),
    SerieConfig("DESLIGNC", "desligamentos", "Novo Caged - sem ajuste", "municipal", "Regional"),
)
SERIES_NACIONAIS = (
    SerieConfig("CAGED12_ADMIS", "admissoes", "CAGED tradicional", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_DESLIG", "desligamentos", "CAGED tradicional", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_SALDO12", "saldo", "CAGED tradicional", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_ADMISN12", "admissoes", "Novo Caged - sem ajuste", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_DESLIGN12", "desligamentos", "Novo Caged - sem ajuste", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_SALDON12", "saldo", "Novo Caged - sem ajuste", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_ADMISNAJU12", "admissoes", "Novo Caged - com ajuste", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_DESLIGNAJU12", "desligamentos", "Novo Caged - com ajuste", "nacional", "Macroeconômico"),
    SerieConfig("CAGED12_SALDONAJU12", "saldo", "Novo Caged - com ajuste", "nacional", "Macroeconômico"),
)
SERIES = {serie.codigo: serie for serie in SERIES_MUNICIPAIS + SERIES_NACIONAIS}
# Única lista de séries que o projeto aceita coletar ou importar.
CODIGOS_SERIES_AUTORIZADAS = frozenset(SERIES)

# Códigos sugeridos no enunciado; a existência de cada um é verificada na API.
SERIES_CANDIDATAS = ("ADMIS", "DESLIG", "ADMISNC", "DESLIGNC")

# Busca local no catálogo (a API não aceita ``contains`` em ``$filter``).
# Regex sobre texto sem acento e minúsculo.
PADROES_BUSCA_NOME = (
    r"\badmiss",
    r"\bdemiss",
    r"\bdeslig",
    r"\bcaged\b",
    r"\bemprego formal",
    r"\bestoque de emprego",
    r"\bvinculos? (empregaticio|ativo)",
    r"\brais\b",
    r"\bpessoal ocupado\b",
)
PADROES_BUSCA_CODIGO = (r"ADMIS", r"DESLIG", r"CAGED", r"RAIS")
PADROES_BUSCA_FONTE = (r"caged", r"\brais\b", r"\bmte\b", r"seprt")

# --- Territórios -----------------------------------------------------------------
NIVEL_MUNICIPIOS = "Municípios"
NIVEL_ESTADOS = "Estados"
NIVEL_BRASIL = "Brasil"
TOTAL_MUNICIPIOS_MA = TOTAL_MUNICIPIOS_UF["MA"]

# Usados apenas em testes de integração e conferências pontuais.
MUNICIPIOS_TESTE = {
    "2111300": "São Luís",
    "2105302": "Imperatriz",
    "2103000": "Caxias",
}

"""Modelos SQLAlchemy 2.x.

Granularidade real dos dados (verificada na etapa 1.5): numa série há no
máximo uma observação por nível territorial × território × mês. As séries
municipais trazem também o total da UF e do Brasil, e as séries de
referência são só nacionais. Por isso ``registros_emprego`` guarda o nível
territorial explicitamente: um total estadual nunca vira dado municipal, e
``municipio_cod`` só é preenchido (e validado por chave estrangeira) no
nível municipal.

A estrutura do banco é criada pelas migrações Alembic (``database/migrations``);
estes modelos as espelham (``alembic check`` confere).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

CONVENCAO_NOMES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

INDICADORES = ("admissoes", "desligamentos", "saldo")
NIVEIS = ("municipio", "estado", "brasil")
FAMILIAS = ("caged_tradicional", "novo_caged")
TIPOS_IMPORTACAO = ("FULL", "INCREMENTAL")
# Procedência: só "validado_ipeadata" alimenta as consultas analíticas (vw_*_validados).
STATUS_PROCEDENCIA = ("validado_ipeadata", "nao_validado", "incompativel")
TIPOS_FONTE = ("acesso", "origem_estatistica", "legado_nao_autorizado")
URL_IPEADATA_REGEX = r"^https://www\.ipeadata\.gov\.br/api/odata4/"
STATUS_IMPORTACAO = ("em_andamento", "concluida", "concluida_com_rejeicoes", "falhou", "interrompida")


def _em(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO_NOMES)


class Carimbos:
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FonteDados(Carimbos, Base):
    __tablename__ = "fontes_dados"
    __table_args__ = (
        CheckConstraint(f"tipo_fonte IN ({_em(TIPOS_FONTE)})", name="tipo_fonte_valido"),
        CheckConstraint("NOT autorizada_para_coleta OR tipo_fonte = 'acesso'", name="autorizada_somente_se_acesso"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    nome: Mapped[str] = mapped_column(Text, unique=True)
    sigla: Mapped[str | None] = mapped_column(Text)
    papel: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    descricao: Mapped[str | None] = mapped_column(Text)
    metodologia: Mapped[str | None] = mapped_column(Text)
    atualizacao: Mapped[str | None] = mapped_column(Text)
    # Regra do projeto: só o IpeaData pode ser fonte de obtenção. As demais são descritivas
    # (origem estatística) ou legado de execuções anteriores, mantido apenas para rastreio.
    tipo_fonte: Mapped[str] = mapped_column(Text, server_default="acesso")
    autorizada_para_coleta: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Municipio(Carimbos, Base):
    __tablename__ = "municipios"
    __table_args__ = (
        CheckConstraint("cod_ibge ~ '^[0-9]{7}$'", name="cod_ibge_7_digitos"),
        CheckConstraint("cod_uf ~ '^[0-9]{2}$'", name="cod_uf_2_digitos"),
        CheckConstraint("left(cod_ibge, 2) = cod_uf", name="cod_ibge_pertence_a_uf"),
        CheckConstraint("uf ~ '^[A-Z]{2}$'", name="uf_sigla"),
        CheckConstraint("area_km2 IS NULL OR area_km2 > 0", name="area_positiva"),
        CheckConstraint(f"status_procedencia IN ({_em(STATUS_PROCEDENCIA)})", name="status_procedencia_valido"),
        CheckConstraint(
            "status_procedencia <> 'validado_ipeadata' OR (snapshot_id IS NOT NULL AND procedencia_verificada_em IS NOT NULL)",
            name="validado_exige_snapshot",
        ),
        Index("ix_municipios_uf_nome", "uf", "nome"),
        Index("ix_municipios_snapshot_id", "snapshot_id"),
    )

    cod_ibge: Mapped[str] = mapped_column(String(7), primary_key=True)
    nome: Mapped[str] = mapped_column(Text)
    uf: Mapped[str] = mapped_column(String(2))
    cod_uf: Mapped[str] = mapped_column(String(2))
    nome_ipeadata: Mapped[str | None] = mapped_column(Text)
    capital: Mapped[bool | None] = mapped_column(Boolean)
    area_km2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    presente_ipeadata: Mapped[bool] = mapped_column(Boolean)
    fonte_referencia_id: Mapped[int] = mapped_column(ForeignKey("fontes_dados.id"))
    referencia_coletada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots_origem.id"))
    status_procedencia: Mapped[str] = mapped_column(Text, server_default="nao_validado")
    procedencia_verificada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fonte_referencia: Mapped[FonteDados] = relationship()


class SerieIndicador(Carimbos, Base):
    __tablename__ = "series_indicadores"
    __table_args__ = (
        UniqueConstraint("fonte_id", "codigo", name="uq_series_indicadores_fonte_codigo"),
        # Garante que a combinação admissões × desligamentos de uma metodologia seja única
        # (base da view de saldo).
        UniqueConstraint(
            "fonte_id", "indicador", "metodologia", "escopo_territorial",
            name="uq_series_indicadores_fonte_indicador_metodologia_escopo",
        ),
        CheckConstraint(f"indicador IN ({_em(INDICADORES)})", name="indicador_valido"),
        CheckConstraint(f"familia_metodologica IN ({_em(FAMILIAS)})", name="familia_valida"),
        CheckConstraint("ajuste IS NULL OR ajuste IN ('sem_ajuste', 'com_ajuste')", name="ajuste_valido"),
        CheckConstraint("escopo_territorial IN ('municipal', 'nacional')", name="escopo_valido"),
        CheckConstraint(
            "cobertura_inicio IS NULL OR cobertura_fim IS NULL OR cobertura_inicio <= cobertura_fim",
            name="cobertura_ordenada",
        ),
        CheckConstraint(f"status_procedencia IN ({_em(STATUS_PROCEDENCIA)})", name="status_procedencia_valido"),
        CheckConstraint(
            "status_procedencia <> 'validado_ipeadata' OR (metadados_ipeadata IS NOT NULL AND procedencia_verificada_em IS NOT NULL)",
            name="validada_exige_metadados",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    fonte_id: Mapped[int] = mapped_column(ForeignKey("fontes_dados.id"))
    fonte_original_id: Mapped[int | None] = mapped_column(ForeignKey("fontes_dados.id"))
    codigo: Mapped[str] = mapped_column(Text)
    nome: Mapped[str] = mapped_column(Text)
    indicador: Mapped[str] = mapped_column(Text)
    metodologia: Mapped[str] = mapped_column(Text)
    familia_metodologica: Mapped[str] = mapped_column(Text)
    ajuste: Mapped[str | None] = mapped_column(Text)
    escopo_territorial: Mapped[str] = mapped_column(Text)
    periodicidade: Mapped[str] = mapped_column(Text)
    unidade: Mapped[str] = mapped_column(Text)
    base_ipeadata: Mapped[str | None] = mapped_column(Text)
    situacao_fonte: Mapped[str | None] = mapped_column(Text)
    serie_atualizada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cobertura_inicio: Mapped[date | None] = mapped_column(Date)
    cobertura_fim: Mapped[date | None] = mapped_column(Date)
    periodos_disponiveis: Mapped[int | None] = mapped_column(Integer)
    # Resposta de Metadados('<codigo>') do IpeaData que comprovou a série, e quando.
    url_metadados: Mapped[str | None] = mapped_column(Text)
    metadados_ipeadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status_procedencia: Mapped[str] = mapped_column(Text, server_default="nao_validado")
    procedencia_verificada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fonte: Mapped[FonteDados] = relationship(foreign_keys=[fonte_id])
    fonte_original: Mapped[FonteDados | None] = relationship(foreign_keys=[fonte_original_id])


class ExecucaoImportacao(Base):
    __tablename__ = "execucoes_importacao"
    __table_args__ = (
        CheckConstraint(f"tipo IN ({_em(TIPOS_IMPORTACAO)})", name="tipo_valido"),
        CheckConstraint(f"status IN ({_em(STATUS_IMPORTACAO)})", name="status_valido"),
        CheckConstraint("finalizado_em IS NULL OR finalizado_em >= iniciado_em", name="periodo_ordenado"),
        Index("ix_execucoes_importacao_iniciado_em", "iniciado_em"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tipo: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    fonte: Mapped[str] = mapped_column(Text)
    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registros_lidos: Mapped[int] = mapped_column(BigInteger, server_default="0")
    registros_validos: Mapped[int] = mapped_column(BigInteger, server_default="0")
    registros_inseridos: Mapped[int] = mapped_column(BigInteger, server_default="0")
    registros_atualizados: Mapped[int] = mapped_column(BigInteger, server_default="0")
    registros_inalterados: Mapped[int] = mapped_column(BigInteger, server_default="0")
    registros_rejeitados: Mapped[int] = mapped_column(BigInteger, server_default="0")
    registros_ausentes_na_origem: Mapped[int] = mapped_column(BigInteger, server_default="0")
    arquivos_processados: Mapped[int] = mapped_column(Integer, server_default="0")
    arquivos_ignorados: Mapped[int] = mapped_column(Integer, server_default="0")
    mensagem_erro: Mapped[str | None] = mapped_column(Text)
    execucao_coleta_id: Mapped[str | None] = mapped_column(Text)
    detalhes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class RegistroEmprego(Carimbos, Base):
    """Uma observação publicada pela fonte (fato)."""

    __tablename__ = "registros_emprego"
    __table_args__ = (
        UniqueConstraint(
            "serie_id", "nivel_territorial", "cod_territorio", "data_referencia",
            name="uq_registros_emprego_chave_natural",
        ),
        CheckConstraint(f"nivel_territorial IN ({_em(NIVEIS)})", name="nivel_valido"),
        CheckConstraint(
            "(nivel_territorial = 'municipio' AND municipio_cod IS NOT NULL AND municipio_cod = cod_territorio)"
            " OR (nivel_territorial <> 'municipio' AND municipio_cod IS NULL)",
            name="municipio_coerente_com_nivel",
        ),
        CheckConstraint(
            "(nivel_territorial = 'estado' AND cod_territorio ~ '^[0-9]{2}$')"
            " OR (nivel_territorial = 'brasil' AND cod_territorio = 'BR')"
            " OR nivel_territorial = 'municipio'",
            name="cod_territorio_coerente_com_nivel",
        ),
        CheckConstraint("EXTRACT(DAY FROM data_referencia) = 1", name="data_primeiro_dia_do_periodo"),
        CheckConstraint("ano = EXTRACT(YEAR FROM data_referencia)", name="ano_coerente"),
        CheckConstraint("mes IS NULL OR mes = EXTRACT(MONTH FROM data_referencia)", name="mes_coerente"),
        # Consultas do dashboard: série de um município ao longo do tempo.
        Index("ix_registros_emprego_municipio_serie_data", "municipio_cod", "serie_id", "data_referencia"),
        # Rankings e totais de um período: todas as observações de uma série/nível num intervalo.
        Index("ix_registros_emprego_serie_nivel_data", "serie_id", "nivel_territorial", "data_referencia"),
        Index("ix_registros_emprego_importacao_id", "importacao_id"),
        Index("ix_registros_emprego_atualizado_por_importacao_id", "atualizado_por_importacao_id"),
        CheckConstraint(f"status_procedencia IN ({_em(STATUS_PROCEDENCIA)})", name="status_procedencia_valido"),
        # Uma observação só pode ser "validada" se estiver ligada ao arquivo bruto que a originou
        # e a uma verificação datada. Quem decide é a auditoria, nunca o importador.
        CheckConstraint(
            "status_procedencia <> 'validado_ipeadata' OR (snapshot_id IS NOT NULL AND procedencia_verificada_em IS NOT NULL)",
            name="validado_exige_snapshot",
        ),
        Index("ix_registros_emprego_snapshot_id", "snapshot_id"),
        Index("ix_registros_emprego_auditoria_id", "auditoria_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    serie_id: Mapped[int] = mapped_column(ForeignKey("series_indicadores.id"))
    nivel_territorial: Mapped[str] = mapped_column(Text)
    cod_territorio: Mapped[str] = mapped_column(Text)
    municipio_cod: Mapped[str | None] = mapped_column(ForeignKey("municipios.cod_ibge"))
    uf: Mapped[str | None] = mapped_column(String(2))
    data_referencia: Mapped[date] = mapped_column(Date)
    ano: Mapped[int] = mapped_column(SmallInteger)
    mes: Mapped[int | None] = mapped_column(SmallInteger)
    # Contagens mensais (máx. observado ~2,6 milhões) cabem em INTEGER; somas viram BIGINT no SQL.
    valor: Mapped[int] = mapped_column(Integer)
    cod_territorio_original: Mapped[str | None] = mapped_column(Text)
    arquivo_bruto: Mapped[str] = mapped_column(Text)
    arquivo_processado: Mapped[str] = mapped_column(Text)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    serie_atualizada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execucao_coleta_id: Mapped[str] = mapped_column(Text)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("execucoes_importacao.id"))
    atualizado_por_importacao_id: Mapped[int] = mapped_column(ForeignKey("execucoes_importacao.id"))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots_origem.id"))
    status_procedencia: Mapped[str] = mapped_column(Text, server_default="nao_validado")
    procedencia_verificada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auditoria_id: Mapped[int | None] = mapped_column(ForeignKey("auditorias_procedencia.id"))

    serie: Mapped[SerieIndicador] = relationship()
    municipio: Mapped[Municipio | None] = relationship()


class RevisaoRegistro(Base):
    """Histórico de valores substituídos por revisões da fonte."""

    __tablename__ = "revisoes_registros"
    __table_args__ = (
        Index("ix_revisoes_registros_registro_id", "registro_id"),
        Index("ix_revisoes_registros_importacao_id", "importacao_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros_emprego.id", ondelete="CASCADE"))
    importacao_id: Mapped[int] = mapped_column(ForeignKey("execucoes_importacao.id"))
    valor_anterior: Mapped[int] = mapped_column(Integer)
    valor_novo: Mapped[int] = mapped_column(Integer)
    arquivo_bruto_anterior: Mapped[str] = mapped_column(Text)
    coletado_em_anterior: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    execucao_coleta_anterior: Mapped[str] = mapped_column(Text)
    arquivo_bruto_novo: Mapped[str] = mapped_column(Text)
    revisado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    registro: Mapped[RegistroEmprego] = relationship()


class ArquivoImportado(Base):
    """Arquivo processado já carregado (base da importação incremental e da retomada)."""

    __tablename__ = "arquivos_importados"
    __table_args__ = (
        UniqueConstraint("caminho", "sha256", name="uq_arquivos_importados_caminho_sha256"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        Index("ix_arquivos_importados_importacao_id", "importacao_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    caminho: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    serie_id: Mapped[int | None] = mapped_column(ForeignKey("series_indicadores.id"))
    linhas: Mapped[int] = mapped_column(Integer)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("execucoes_importacao.id"))
    importado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InconsistenciaDados(Base):
    __tablename__ = "inconsistencias_dados"
    __table_args__ = (
        Index("ix_inconsistencias_dados_importacao_id", "importacao_id"),
        Index("ix_inconsistencias_dados_tipo", "tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("execucoes_importacao.id"))
    fonte: Mapped[str] = mapped_column(Text)
    arquivo: Mapped[str | None] = mapped_column(Text)
    identificacao_registro: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(Text)
    descricao: Mapped[str] = mapped_column(Text)
    dados: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    identificado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SnapshotOrigem(Base):
    """Resposta do IpeaData que originou observações: URL, hash, horário e resultado da verificação.

    Um registro por série e coleta (``arquivo_bruto`` é o primeiro arquivo da resposta) ou, com
    ``tipo = 'territorios'``, por consulta do cadastro de municípios.
    """

    __tablename__ = "snapshots_origem"
    __table_args__ = (
        UniqueConstraint("arquivo_bruto", name="uq_snapshots_origem_arquivo_bruto"),
        CheckConstraint("tipo IN ('serie', 'territorios')", name="tipo_valido"),
        CheckConstraint("tipo <> 'serie' OR serie_codigo IS NOT NULL", name="serie_exige_codigo"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint(f"url ~ '{URL_IPEADATA_REGEX}'", name="url_do_ipeadata"),
        CheckConstraint(f"status_procedencia IN ({_em(STATUS_PROCEDENCIA)})", name="status_procedencia_valido"),
        CheckConstraint(
            "status_procedencia <> 'validado_ipeadata' OR verificado_em IS NOT NULL", name="validado_exige_data"
        ),
        Index("ix_snapshots_origem_serie_codigo", "serie_codigo"),
        Index("ix_snapshots_origem_auditoria_id", "auditoria_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tipo: Mapped[str] = mapped_column(Text)
    serie_codigo: Mapped[str | None] = mapped_column(Text)
    arquivo_bruto: Mapped[str] = mapped_column(Text)
    arquivos: Mapped[list[str]] = mapped_column(JSONB)
    paginas: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    status_http: Mapped[int | None] = mapped_column(SmallInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    execucao_coleta_id: Mapped[str | None] = mapped_column(Text)
    serie_atualizada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadados: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status_procedencia: Mapped[str] = mapped_column(Text, server_default="nao_validado")
    verificado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auditoria_id: Mapped[int | None] = mapped_column(ForeignKey("auditorias_procedencia.id"))
    evidencia: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditoriaProcedencia(Base):
    """Cada execução da auditoria de procedência (comparação com as respostas do IpeaData)."""

    __tablename__ = "auditorias_procedencia"
    __table_args__ = (
        CheckConstraint("status IN ('em_andamento', 'concluida', 'incompleta', 'falhou')", name="status_valido"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    iniciada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalizada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resumo: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")

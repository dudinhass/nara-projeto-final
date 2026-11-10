"""Esquema inicial: cadastros, observações, rastreabilidade e view de movimentação.

Gerada com ``alembic revision --autogenerate`` a partir de ``banco/modelos.py``
e revisada; a view ``vw_movimentacao_mensal`` foi acrescentada à mão.

Revision ID: 0001
Revises:
Create Date: 2026-10-25 21:06:36.446577+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Uma linha por território × mês × metodologia, com admissões e desligamentos lado a lado.
# O agrupamento por fonte + metodologia + escopo impede misturar CAGED tradicional e Novo
# Caged (ou séries com e sem ajuste); a restrição única de series_indicadores garante no
# máximo uma série de cada indicador por grupo. O saldo fica NULL quando falta um dos dois.
VIEW_MOVIMENTACAO = """
CREATE VIEW vw_movimentacao_mensal AS
WITH obs AS (
    SELECT r.nivel_territorial, r.cod_territorio, r.municipio_cod, r.uf, r.data_referencia, r.ano, r.mes,
           s.fonte_id, s.metodologia, s.familia_metodologica, s.escopo_territorial, s.indicador, s.codigo, r.valor
    FROM registros_emprego r
    JOIN series_indicadores s ON s.id = r.serie_id
    WHERE s.indicador IN ('admissoes', 'desligamentos')
)
SELECT nivel_territorial, cod_territorio, municipio_cod, uf, data_referencia, ano, mes,
       fonte_id, metodologia, familia_metodologica, escopo_territorial,
       max(valor) FILTER (WHERE indicador = 'admissoes') AS admissoes,
       max(valor) FILTER (WHERE indicador = 'desligamentos') AS desligamentos,
       max(valor) FILTER (WHERE indicador = 'admissoes')
         - max(valor) FILTER (WHERE indicador = 'desligamentos') AS saldo,
       max(codigo) FILTER (WHERE indicador = 'admissoes') AS serie_admissoes,
       max(codigo) FILTER (WHERE indicador = 'desligamentos') AS serie_desligamentos
FROM obs
GROUP BY nivel_territorial, cod_territorio, municipio_cod, uf, data_referencia, ano, mes,
         fonte_id, metodologia, familia_metodologica, escopo_territorial
"""

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('execucoes_importacao',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('tipo', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('fonte', sa.Text(), nullable=False),
    sa.Column('iniciado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finalizado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('registros_lidos', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('registros_validos', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('registros_inseridos', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('registros_atualizados', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('registros_inalterados', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('registros_rejeitados', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('registros_ausentes_na_origem', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('arquivos_processados', sa.Integer(), server_default='0', nullable=False),
    sa.Column('arquivos_ignorados', sa.Integer(), server_default='0', nullable=False),
    sa.Column('mensagem_erro', sa.Text(), nullable=True),
    sa.Column('execucao_coleta_id', sa.Text(), nullable=True),
    sa.Column('detalhes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.CheckConstraint("status IN ('em_andamento', 'concluida', 'concluida_com_rejeicoes', 'falhou', 'interrompida')", name=op.f('ck_execucoes_importacao_status_valido')),
    sa.CheckConstraint("tipo IN ('FULL', 'INCREMENTAL')", name=op.f('ck_execucoes_importacao_tipo_valido')),
    sa.CheckConstraint('finalizado_em IS NULL OR finalizado_em >= iniciado_em', name=op.f('ck_execucoes_importacao_periodo_ordenado')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_execucoes_importacao'))
    )
    op.create_index('ix_execucoes_importacao_iniciado_em', 'execucoes_importacao', ['iniciado_em'], unique=False)
    op.create_table('fontes_dados',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('nome', sa.Text(), nullable=False),
    sa.Column('sigla', sa.Text(), nullable=True),
    sa.Column('papel', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('descricao', sa.Text(), nullable=True),
    sa.Column('metodologia', sa.Text(), nullable=True),
    sa.Column('atualizacao', sa.Text(), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fontes_dados')),
    sa.UniqueConstraint('nome', name=op.f('uq_fontes_dados_nome'))
    )
    op.create_table('inconsistencias_dados',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('importacao_id', sa.BigInteger(), nullable=False),
    sa.Column('fonte', sa.Text(), nullable=False),
    sa.Column('arquivo', sa.Text(), nullable=True),
    sa.Column('identificacao_registro', sa.Text(), nullable=True),
    sa.Column('tipo', sa.Text(), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=False),
    sa.Column('dados', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('identificado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['importacao_id'], ['execucoes_importacao.id'], name=op.f('fk_inconsistencias_dados_importacao_id_execucoes_importacao')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inconsistencias_dados'))
    )
    op.create_index('ix_inconsistencias_dados_importacao_id', 'inconsistencias_dados', ['importacao_id'], unique=False)
    op.create_index('ix_inconsistencias_dados_tipo', 'inconsistencias_dados', ['tipo'], unique=False)
    op.create_table('municipios',
    sa.Column('cod_ibge', sa.String(length=7), nullable=False),
    sa.Column('nome', sa.Text(), nullable=False),
    sa.Column('uf', sa.String(length=2), nullable=False),
    sa.Column('cod_uf', sa.String(length=2), nullable=False),
    sa.Column('nome_ipeadata', sa.Text(), nullable=True),
    sa.Column('capital', sa.Boolean(), nullable=True),
    sa.Column('area_km2', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('presente_ipeadata', sa.Boolean(), nullable=False),
    sa.Column('fonte_referencia_id', sa.Integer(), nullable=False),
    sa.Column('referencia_coletada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("cod_ibge ~ '^[0-9]{7}$'", name=op.f('ck_municipios_cod_ibge_7_digitos')),
    sa.CheckConstraint("cod_uf ~ '^[0-9]{2}$'", name=op.f('ck_municipios_cod_uf_2_digitos')),
    sa.CheckConstraint("uf ~ '^[A-Z]{2}$'", name=op.f('ck_municipios_uf_sigla')),
    sa.CheckConstraint('area_km2 IS NULL OR area_km2 > 0', name=op.f('ck_municipios_area_positiva')),
    sa.CheckConstraint('left(cod_ibge, 2) = cod_uf', name=op.f('ck_municipios_cod_ibge_pertence_a_uf')),
    sa.ForeignKeyConstraint(['fonte_referencia_id'], ['fontes_dados.id'], name=op.f('fk_municipios_fonte_referencia_id_fontes_dados')),
    sa.PrimaryKeyConstraint('cod_ibge', name=op.f('pk_municipios'))
    )
    op.create_index('ix_municipios_uf_nome', 'municipios', ['uf', 'nome'], unique=False)
    op.create_table('series_indicadores',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('fonte_id', sa.Integer(), nullable=False),
    sa.Column('fonte_original_id', sa.Integer(), nullable=True),
    sa.Column('codigo', sa.Text(), nullable=False),
    sa.Column('nome', sa.Text(), nullable=False),
    sa.Column('indicador', sa.Text(), nullable=False),
    sa.Column('metodologia', sa.Text(), nullable=False),
    sa.Column('familia_metodologica', sa.Text(), nullable=False),
    sa.Column('ajuste', sa.Text(), nullable=True),
    sa.Column('escopo_territorial', sa.Text(), nullable=False),
    sa.Column('periodicidade', sa.Text(), nullable=False),
    sa.Column('unidade', sa.Text(), nullable=False),
    sa.Column('base_ipeadata', sa.Text(), nullable=True),
    sa.Column('situacao_fonte', sa.Text(), nullable=True),
    sa.Column('serie_atualizada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cobertura_inicio', sa.Date(), nullable=True),
    sa.Column('cobertura_fim', sa.Date(), nullable=True),
    sa.Column('periodos_disponiveis', sa.Integer(), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("ajuste IS NULL OR ajuste IN ('sem_ajuste', 'com_ajuste')", name=op.f('ck_series_indicadores_ajuste_valido')),
    sa.CheckConstraint("escopo_territorial IN ('municipal', 'nacional')", name=op.f('ck_series_indicadores_escopo_valido')),
    sa.CheckConstraint("familia_metodologica IN ('caged_tradicional', 'novo_caged')", name=op.f('ck_series_indicadores_familia_valida')),
    sa.CheckConstraint("indicador IN ('admissoes', 'desligamentos', 'saldo')", name=op.f('ck_series_indicadores_indicador_valido')),
    sa.CheckConstraint('cobertura_inicio IS NULL OR cobertura_fim IS NULL OR cobertura_inicio <= cobertura_fim', name=op.f('ck_series_indicadores_cobertura_ordenada')),
    sa.ForeignKeyConstraint(['fonte_id'], ['fontes_dados.id'], name=op.f('fk_series_indicadores_fonte_id_fontes_dados')),
    sa.ForeignKeyConstraint(['fonte_original_id'], ['fontes_dados.id'], name=op.f('fk_series_indicadores_fonte_original_id_fontes_dados')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_series_indicadores')),
    sa.UniqueConstraint('fonte_id', 'codigo', name='uq_series_indicadores_fonte_codigo'),
    sa.UniqueConstraint('fonte_id', 'indicador', 'metodologia', 'escopo_territorial', name='uq_series_indicadores_fonte_indicador_metodologia_escopo')
    )
    op.create_table('arquivos_importados',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('caminho', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('serie_id', sa.Integer(), nullable=True),
    sa.Column('linhas', sa.Integer(), nullable=False),
    sa.Column('importacao_id', sa.BigInteger(), nullable=False),
    sa.Column('importado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_arquivos_importados_sha256_hex')),
    sa.ForeignKeyConstraint(['importacao_id'], ['execucoes_importacao.id'], name=op.f('fk_arquivos_importados_importacao_id_execucoes_importacao')),
    sa.ForeignKeyConstraint(['serie_id'], ['series_indicadores.id'], name=op.f('fk_arquivos_importados_serie_id_series_indicadores')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arquivos_importados')),
    sa.UniqueConstraint('caminho', 'sha256', name='uq_arquivos_importados_caminho_sha256')
    )
    op.create_index('ix_arquivos_importados_importacao_id', 'arquivos_importados', ['importacao_id'], unique=False)
    op.create_table('registros_emprego',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('serie_id', sa.Integer(), nullable=False),
    sa.Column('nivel_territorial', sa.Text(), nullable=False),
    sa.Column('cod_territorio', sa.Text(), nullable=False),
    sa.Column('municipio_cod', sa.String(length=7), nullable=True),
    sa.Column('uf', sa.String(length=2), nullable=True),
    sa.Column('data_referencia', sa.Date(), nullable=False),
    sa.Column('ano', sa.SmallInteger(), nullable=False),
    sa.Column('mes', sa.SmallInteger(), nullable=True),
    sa.Column('valor', sa.Integer(), nullable=False),
    sa.Column('cod_territorio_original', sa.Text(), nullable=True),
    sa.Column('arquivo_bruto', sa.Text(), nullable=False),
    sa.Column('arquivo_processado', sa.Text(), nullable=False),
    sa.Column('coletado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('serie_atualizada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('execucao_coleta_id', sa.Text(), nullable=False),
    sa.Column('importacao_id', sa.BigInteger(), nullable=False),
    sa.Column('atualizado_por_importacao_id', sa.BigInteger(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(nivel_territorial = 'estado' AND cod_territorio ~ '^[0-9]{2}$') OR (nivel_territorial = 'brasil' AND cod_territorio = 'BR') OR nivel_territorial = 'municipio'", name=op.f('ck_registros_emprego_cod_territorio_coerente_com_nivel')),
    sa.CheckConstraint("(nivel_territorial = 'municipio' AND municipio_cod IS NOT NULL AND municipio_cod = cod_territorio) OR (nivel_territorial <> 'municipio' AND municipio_cod IS NULL)", name=op.f('ck_registros_emprego_municipio_coerente_com_nivel')),
    sa.CheckConstraint("nivel_territorial IN ('municipio', 'estado', 'brasil')", name=op.f('ck_registros_emprego_nivel_valido')),
    sa.CheckConstraint('EXTRACT(DAY FROM data_referencia) = 1', name=op.f('ck_registros_emprego_data_primeiro_dia_do_periodo')),
    sa.CheckConstraint('ano = EXTRACT(YEAR FROM data_referencia)', name=op.f('ck_registros_emprego_ano_coerente')),
    sa.CheckConstraint('mes IS NULL OR mes = EXTRACT(MONTH FROM data_referencia)', name=op.f('ck_registros_emprego_mes_coerente')),
    sa.ForeignKeyConstraint(['atualizado_por_importacao_id'], ['execucoes_importacao.id'], name=op.f('fk_registros_emprego_atualizado_por_importacao_id_execucoes_importacao')),
    sa.ForeignKeyConstraint(['importacao_id'], ['execucoes_importacao.id'], name=op.f('fk_registros_emprego_importacao_id_execucoes_importacao')),
    sa.ForeignKeyConstraint(['municipio_cod'], ['municipios.cod_ibge'], name=op.f('fk_registros_emprego_municipio_cod_municipios')),
    sa.ForeignKeyConstraint(['serie_id'], ['series_indicadores.id'], name=op.f('fk_registros_emprego_serie_id_series_indicadores')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_registros_emprego')),
    sa.UniqueConstraint('serie_id', 'nivel_territorial', 'cod_territorio', 'data_referencia', name='uq_registros_emprego_chave_natural')
    )
    op.create_index('ix_registros_emprego_atualizado_por_importacao_id', 'registros_emprego', ['atualizado_por_importacao_id'], unique=False)
    op.create_index('ix_registros_emprego_importacao_id', 'registros_emprego', ['importacao_id'], unique=False)
    op.create_index('ix_registros_emprego_municipio_serie_data', 'registros_emprego', ['municipio_cod', 'serie_id', 'data_referencia'], unique=False)
    op.create_index('ix_registros_emprego_serie_nivel_data', 'registros_emprego', ['serie_id', 'nivel_territorial', 'data_referencia'], unique=False)
    op.create_table('revisoes_registros',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('registro_id', sa.BigInteger(), nullable=False),
    sa.Column('importacao_id', sa.BigInteger(), nullable=False),
    sa.Column('valor_anterior', sa.Integer(), nullable=False),
    sa.Column('valor_novo', sa.Integer(), nullable=False),
    sa.Column('arquivo_bruto_anterior', sa.Text(), nullable=False),
    sa.Column('coletado_em_anterior', sa.DateTime(timezone=True), nullable=False),
    sa.Column('execucao_coleta_anterior', sa.Text(), nullable=False),
    sa.Column('arquivo_bruto_novo', sa.Text(), nullable=False),
    sa.Column('revisado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['importacao_id'], ['execucoes_importacao.id'], name=op.f('fk_revisoes_registros_importacao_id_execucoes_importacao')),
    sa.ForeignKeyConstraint(['registro_id'], ['registros_emprego.id'], name=op.f('fk_revisoes_registros_registro_id_registros_emprego'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_revisoes_registros'))
    )
    op.create_index('ix_revisoes_registros_importacao_id', 'revisoes_registros', ['importacao_id'], unique=False)
    op.create_index('ix_revisoes_registros_registro_id', 'revisoes_registros', ['registro_id'], unique=False)
    op.execute(VIEW_MOVIMENTACAO)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vw_movimentacao_mensal")
    op.drop_index('ix_revisoes_registros_registro_id', table_name='revisoes_registros')
    op.drop_index('ix_revisoes_registros_importacao_id', table_name='revisoes_registros')
    op.drop_table('revisoes_registros')
    op.drop_index('ix_registros_emprego_serie_nivel_data', table_name='registros_emprego')
    op.drop_index('ix_registros_emprego_municipio_serie_data', table_name='registros_emprego')
    op.drop_index('ix_registros_emprego_importacao_id', table_name='registros_emprego')
    op.drop_index('ix_registros_emprego_atualizado_por_importacao_id', table_name='registros_emprego')
    op.drop_table('registros_emprego')
    op.drop_index('ix_arquivos_importados_importacao_id', table_name='arquivos_importados')
    op.drop_table('arquivos_importados')
    op.drop_table('series_indicadores')
    op.drop_index('ix_municipios_uf_nome', table_name='municipios')
    op.drop_table('municipios')
    op.drop_index('ix_inconsistencias_dados_tipo', table_name='inconsistencias_dados')
    op.drop_index('ix_inconsistencias_dados_importacao_id', table_name='inconsistencias_dados')
    op.drop_table('inconsistencias_dados')
    op.drop_table('fontes_dados')
    op.drop_index('ix_execucoes_importacao_iniciado_em', table_name='execucoes_importacao')
    op.drop_table('execucoes_importacao')

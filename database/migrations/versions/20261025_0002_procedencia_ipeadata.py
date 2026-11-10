"""Procedência: só dados do IpeaData alimentam as consultas analíticas.

Gerada com ``alembic revision --autogenerate`` e completada à mão (o autogenerate não detecta
restrições CHECK, gatilhos, views nem atualização de dados):

* ``fontes_dados`` passa a classificar cada fonte (acesso / origem estatística / legado não
  autorizado) e a dizer se pode ser fonte de obtenção; só o IpeaData pode;
* ``snapshots_origem`` guarda, por resposta do IpeaData, a URL, o hash e o resultado da verificação;
* observações, séries e municípios ganham ``status_procedencia`` (nada é apagado; tudo que já
  existe começa como ``nao_validado`` até a auditoria comparar com o IpeaData);
* gatilhos impedem fonte não autorizada em séries/municípios e snapshot de outra série;
* ``vw_registros_validados``, ``vw_municipios_validados`` e ``vw_movimentacao_mensal`` expõem
  somente dados validados. Consultas analíticas devem ler apenas essas views.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25 22:03:05.844117+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# View de movimentação da revisão 0001, restaurada no downgrade.
VIEW_MOVIMENTACAO_0001 = """
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

# Só entra aqui o que foi validado contra o IpeaData: observação, série, snapshot de origem,
# município (quando municipal) e fonte autorizada, tudo ao mesmo tempo.
VIEW_REGISTROS_VALIDADOS = """
CREATE VIEW vw_registros_validados AS
SELECT r.id, r.serie_id, r.nivel_territorial, r.cod_territorio, r.municipio_cod, r.uf, r.data_referencia,
       r.ano, r.mes, r.valor, r.snapshot_id, r.coletado_em, r.execucao_coleta_id, r.importacao_id,
       r.atualizado_por_importacao_id
FROM registros_emprego r
JOIN series_indicadores s ON s.id = r.serie_id AND s.status_procedencia = 'validado_ipeadata'
JOIN fontes_dados f ON f.id = s.fonte_id AND f.autorizada_para_coleta
JOIN snapshots_origem sn ON sn.id = r.snapshot_id AND sn.status_procedencia = 'validado_ipeadata'
WHERE r.status_procedencia = 'validado_ipeadata'
  AND (r.nivel_territorial <> 'municipio'
       OR EXISTS (SELECT 1 FROM municipios m
                  WHERE m.cod_ibge = r.municipio_cod AND m.status_procedencia = 'validado_ipeadata'))
"""

VIEW_MUNICIPIOS_VALIDADOS = """
CREATE VIEW vw_municipios_validados AS
SELECT m.cod_ibge, m.nome, m.uf, m.cod_uf, m.capital, m.area_km2, m.snapshot_id
FROM municipios m
JOIN fontes_dados f ON f.id = m.fonte_referencia_id AND f.autorizada_para_coleta
JOIN snapshots_origem sn ON sn.id = m.snapshot_id AND sn.status_procedencia = 'validado_ipeadata'
WHERE m.status_procedencia = 'validado_ipeadata'
"""

VIEW_MOVIMENTACAO = """
CREATE VIEW vw_movimentacao_mensal AS
WITH obs AS (
    SELECT v.nivel_territorial, v.cod_territorio, v.municipio_cod, v.uf, v.data_referencia, v.ano, v.mes,
           s.fonte_id, s.metodologia, s.familia_metodologica, s.escopo_territorial, s.indicador, s.codigo, v.valor
    FROM vw_registros_validados v
    JOIN series_indicadores s ON s.id = v.serie_id
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

FUNCAO_FONTE_AUTORIZADA = """
CREATE FUNCTION trg_fonte_autorizada() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    fonte_id integer;
BEGIN
    -- IF/ELSE (e não CASE): o PL/pgSQL só resolve o campo do ramo executado; cada tabela tem uma coluna diferente.
    IF TG_TABLE_NAME = 'series_indicadores' THEN
        fonte_id := NEW.fonte_id;
    ELSE
        fonte_id := NEW.fonte_referencia_id;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM fontes_dados WHERE id = fonte_id AND autorizada_para_coleta) THEN
        RAISE EXCEPTION 'Fonte % nao autorizada para obtencao de dados (somente IpeaData)', fonte_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$
"""

FUNCAO_SNAPSHOT_COERENTE = """
CREATE FUNCTION trg_registro_snapshot_coerente() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.snapshot_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM snapshots_origem sn JOIN series_indicadores s ON s.id = NEW.serie_id
        WHERE sn.id = NEW.snapshot_id AND sn.tipo = 'serie' AND sn.serie_codigo = s.codigo
    ) THEN
        RAISE EXCEPTION 'Snapshot % nao pertence a serie do registro (serie_id %)', NEW.snapshot_id, NEW.serie_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$
"""

CHECKS = [
    ("fontes_dados", "tipo_fonte_valido",
     "tipo_fonte IN ('acesso', 'origem_estatistica', 'legado_nao_autorizado')"),
    ("fontes_dados", "autorizada_somente_se_acesso", "NOT autorizada_para_coleta OR tipo_fonte = 'acesso'"),
    ("municipios", "status_procedencia_valido",
     "status_procedencia IN ('validado_ipeadata', 'nao_validado', 'incompativel')"),
    ("municipios", "validado_exige_snapshot",
     "status_procedencia <> 'validado_ipeadata' OR (snapshot_id IS NOT NULL AND procedencia_verificada_em IS NOT NULL)"),
    ("series_indicadores", "status_procedencia_valido",
     "status_procedencia IN ('validado_ipeadata', 'nao_validado', 'incompativel')"),
    ("series_indicadores", "validada_exige_metadados",
     "status_procedencia <> 'validado_ipeadata' OR (metadados_ipeadata IS NOT NULL AND procedencia_verificada_em IS NOT NULL)"),
    ("registros_emprego", "status_procedencia_valido",
     "status_procedencia IN ('validado_ipeadata', 'nao_validado', 'incompativel')"),
    ("registros_emprego", "validado_exige_snapshot",
     "status_procedencia <> 'validado_ipeadata' OR (snapshot_id IS NOT NULL AND procedencia_verificada_em IS NOT NULL)"),
]

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('auditorias_procedencia',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('iniciada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finalizada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resumo', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.CheckConstraint("status IN ('em_andamento', 'concluida', 'incompleta', 'falhou')", name=op.f('ck_auditorias_procedencia_status_valido')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auditorias_procedencia'))
    )
    op.create_table('snapshots_origem',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('tipo', sa.Text(), nullable=False),
    sa.Column('serie_codigo', sa.Text(), nullable=True),
    sa.Column('arquivo_bruto', sa.Text(), nullable=False),
    sa.Column('arquivos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('paginas', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status_http', sa.SmallInteger(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('bytes', sa.BigInteger(), nullable=True),
    sa.Column('coletado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('execucao_coleta_id', sa.Text(), nullable=True),
    sa.Column('serie_atualizada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metadados', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status_procedencia', sa.Text(), server_default='nao_validado', nullable=False),
    sa.Column('verificado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('auditoria_id', sa.BigInteger(), nullable=True),
    sa.Column('evidencia', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_snapshots_origem_sha256_hex')),
    sa.CheckConstraint("status_procedencia <> 'validado_ipeadata' OR verificado_em IS NOT NULL", name=op.f('ck_snapshots_origem_validado_exige_data')),
    sa.CheckConstraint("status_procedencia IN ('validado_ipeadata', 'nao_validado', 'incompativel')", name=op.f('ck_snapshots_origem_status_procedencia_valido')),
    sa.CheckConstraint("tipo <> 'serie' OR serie_codigo IS NOT NULL", name=op.f('ck_snapshots_origem_serie_exige_codigo')),
    sa.CheckConstraint("tipo IN ('serie', 'territorios')", name=op.f('ck_snapshots_origem_tipo_valido')),
    sa.CheckConstraint("url ~ '^https://www\\.ipeadata\\.gov\\.br/api/odata4/'", name=op.f('ck_snapshots_origem_url_do_ipeadata')),
    sa.ForeignKeyConstraint(['auditoria_id'], ['auditorias_procedencia.id'], name=op.f('fk_snapshots_origem_auditoria_id_auditorias_procedencia')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_snapshots_origem')),
    sa.UniqueConstraint('arquivo_bruto', name='uq_snapshots_origem_arquivo_bruto')
    )
    op.create_index('ix_snapshots_origem_auditoria_id', 'snapshots_origem', ['auditoria_id'], unique=False)
    op.create_index('ix_snapshots_origem_serie_codigo', 'snapshots_origem', ['serie_codigo'], unique=False)
    op.add_column('fontes_dados', sa.Column('tipo_fonte', sa.Text(), server_default='acesso', nullable=False))
    op.add_column('fontes_dados', sa.Column('autorizada_para_coleta', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('municipios', sa.Column('snapshot_id', sa.BigInteger(), nullable=True))
    op.add_column('municipios', sa.Column('status_procedencia', sa.Text(), server_default='nao_validado', nullable=False))
    op.add_column('municipios', sa.Column('procedencia_verificada_em', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_municipios_snapshot_id', 'municipios', ['snapshot_id'], unique=False)
    op.create_foreign_key(op.f('fk_municipios_snapshot_id_snapshots_origem'), 'municipios', 'snapshots_origem', ['snapshot_id'], ['id'])
    op.add_column('registros_emprego', sa.Column('snapshot_id', sa.BigInteger(), nullable=True))
    op.add_column('registros_emprego', sa.Column('status_procedencia', sa.Text(), server_default='nao_validado', nullable=False))
    op.add_column('registros_emprego', sa.Column('procedencia_verificada_em', sa.DateTime(timezone=True), nullable=True))
    op.add_column('registros_emprego', sa.Column('auditoria_id', sa.BigInteger(), nullable=True))
    op.create_index('ix_registros_emprego_auditoria_id', 'registros_emprego', ['auditoria_id'], unique=False)
    op.create_index('ix_registros_emprego_snapshot_id', 'registros_emprego', ['snapshot_id'], unique=False)
    op.create_foreign_key(op.f('fk_registros_emprego_auditoria_id_auditorias_procedencia'), 'registros_emprego', 'auditorias_procedencia', ['auditoria_id'], ['id'])
    op.create_foreign_key(op.f('fk_registros_emprego_snapshot_id_snapshots_origem'), 'registros_emprego', 'snapshots_origem', ['snapshot_id'], ['id'])
    op.add_column('series_indicadores', sa.Column('url_metadados', sa.Text(), nullable=True))
    op.add_column('series_indicadores', sa.Column('metadados_ipeadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('series_indicadores', sa.Column('status_procedencia', sa.Text(), server_default='nao_validado', nullable=False))
    op.add_column('series_indicadores', sa.Column('procedencia_verificada_em', sa.DateTime(timezone=True), nullable=True))

    # --- Classificação das fontes já cadastradas (nenhuma linha é apagada) ---
    op.execute("UPDATE fontes_dados SET tipo_fonte = 'acesso', autorizada_para_coleta = true WHERE nome = 'IpeaData'")
    op.execute("UPDATE fontes_dados SET tipo_fonte = 'origem_estatistica', autorizada_para_coleta = false "
               "WHERE nome = 'MTE/Caged'")
    # A lista de municípios foi obtida do IBGE nas etapas anteriores: fica registrada como legado
    # não autorizado. A importação seguinte troca a referência dos municípios para o IpeaData.
    op.execute("UPDATE fontes_dados SET tipo_fonte = 'legado_nao_autorizado', autorizada_para_coleta = false "
               "WHERE nome LIKE 'IBGE%'")

    for tabela, nome, condicao in CHECKS:
        op.create_check_constraint(op.f(f'ck_{tabela}_{nome}'), tabela, condicao)

    # --- Gatilhos ---
    op.execute(FUNCAO_FONTE_AUTORIZADA)
    op.execute("CREATE TRIGGER series_fonte_autorizada BEFORE INSERT OR UPDATE OF fonte_id ON series_indicadores "
               "FOR EACH ROW EXECUTE FUNCTION trg_fonte_autorizada()")
    op.execute("CREATE TRIGGER municipios_fonte_autorizada BEFORE INSERT OR UPDATE OF fonte_referencia_id ON municipios "
               "FOR EACH ROW EXECUTE FUNCTION trg_fonte_autorizada()")
    op.execute(FUNCAO_SNAPSHOT_COERENTE)
    op.execute("CREATE TRIGGER registros_snapshot_coerente BEFORE INSERT OR UPDATE OF snapshot_id, serie_id ON registros_emprego "
               "FOR EACH ROW EXECUTE FUNCTION trg_registro_snapshot_coerente()")

    # --- Views: a camada analítica só enxerga dados validados ---
    op.execute("DROP VIEW vw_movimentacao_mensal")
    op.execute(VIEW_REGISTROS_VALIDADOS)
    op.execute(VIEW_MUNICIPIOS_VALIDADOS)
    op.execute(VIEW_MOVIMENTACAO)


def downgrade() -> None:
    op.execute("DROP VIEW vw_movimentacao_mensal")
    op.execute("DROP VIEW vw_municipios_validados")
    op.execute("DROP VIEW vw_registros_validados")
    op.execute(VIEW_MOVIMENTACAO_0001)
    op.execute("DROP TRIGGER registros_snapshot_coerente ON registros_emprego")
    op.execute("DROP FUNCTION trg_registro_snapshot_coerente()")
    op.execute("DROP TRIGGER municipios_fonte_autorizada ON municipios")
    op.execute("DROP TRIGGER series_fonte_autorizada ON series_indicadores")
    op.execute("DROP FUNCTION trg_fonte_autorizada()")
    for tabela, nome, _ in reversed(CHECKS):
        op.drop_constraint(op.f(f'ck_{tabela}_{nome}'), tabela, type_='check')
    op.drop_column('series_indicadores', 'procedencia_verificada_em')
    op.drop_column('series_indicadores', 'status_procedencia')
    op.drop_column('series_indicadores', 'metadados_ipeadata')
    op.drop_column('series_indicadores', 'url_metadados')
    op.drop_constraint(op.f('fk_registros_emprego_snapshot_id_snapshots_origem'), 'registros_emprego', type_='foreignkey')
    op.drop_constraint(op.f('fk_registros_emprego_auditoria_id_auditorias_procedencia'), 'registros_emprego', type_='foreignkey')
    op.drop_index('ix_registros_emprego_snapshot_id', table_name='registros_emprego')
    op.drop_index('ix_registros_emprego_auditoria_id', table_name='registros_emprego')
    op.drop_column('registros_emprego', 'auditoria_id')
    op.drop_column('registros_emprego', 'procedencia_verificada_em')
    op.drop_column('registros_emprego', 'status_procedencia')
    op.drop_column('registros_emprego', 'snapshot_id')
    op.drop_constraint(op.f('fk_municipios_snapshot_id_snapshots_origem'), 'municipios', type_='foreignkey')
    op.drop_index('ix_municipios_snapshot_id', table_name='municipios')
    op.drop_column('municipios', 'procedencia_verificada_em')
    op.drop_column('municipios', 'status_procedencia')
    op.drop_column('municipios', 'snapshot_id')
    op.drop_column('fontes_dados', 'autorizada_para_coleta')
    op.drop_column('fontes_dados', 'tipo_fonte')
    op.drop_index('ix_snapshots_origem_serie_codigo', table_name='snapshots_origem')
    op.drop_index('ix_snapshots_origem_auditoria_id', table_name='snapshots_origem')
    op.drop_table('snapshots_origem')
    op.drop_table('auditorias_procedencia')

-- Totais mensais da UF: valor oficial publicado para o estado e soma dos municípios, lado a lado.
-- Parâmetros: :uf, :cod_uf, :metodologia, :inicio, :fim
WITH estado AS (
    SELECT data_referencia, admissoes, desligamentos, saldo
    FROM vw_movimentacao_mensal
    WHERE nivel_territorial = 'estado'
      AND cod_territorio = :cod_uf
      AND escopo_territorial = 'municipal'
      AND metodologia = :metodologia
      AND data_referencia BETWEEN :inicio AND :fim
), soma_municipios AS (
    SELECT data_referencia,
           sum(admissoes) AS admissoes,
           sum(desligamentos) AS desligamentos,
           sum(saldo) AS saldo,
           count(*) AS municipios_com_observacao
    FROM vw_movimentacao_mensal
    WHERE nivel_territorial = 'municipio'
      AND uf = :uf
      AND escopo_territorial = 'municipal'
      AND metodologia = :metodologia
      AND data_referencia BETWEEN :inicio AND :fim
    GROUP BY data_referencia
)
SELECT coalesce(e.data_referencia, s.data_referencia) AS data_referencia,
       e.admissoes AS admissoes_uf,
       e.desligamentos AS desligamentos_uf,
       e.saldo AS saldo_uf,
       s.admissoes AS admissoes_soma_municipios,
       s.desligamentos AS desligamentos_soma_municipios,
       s.saldo AS saldo_soma_municipios,
       s.municipios_com_observacao
FROM estado e
FULL JOIN soma_municipios s ON s.data_referencia = e.data_referencia
ORDER BY 1;

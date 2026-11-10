-- Série mensal de um território com grade completa de meses: mês sem observação aparece
-- com valores NULL e situação 'sem_observacao' (a ausência não vira zero).
-- Parâmetros: :nivel, :cod_territorio, :metodologia, :escopo, :inicio, :fim
WITH meses AS (
    SELECT CAST(d AS date) AS data_referencia
    FROM generate_series(CAST(:inicio AS date), CAST(:fim AS date), interval '1 month') AS d
)
SELECT m.data_referencia,
       CAST(EXTRACT(YEAR FROM m.data_referencia) AS int) AS ano,
       CAST(EXTRACT(MONTH FROM m.data_referencia) AS int) AS mes,
       v.admissoes,
       v.desligamentos,
       v.saldo,
       CASE
           WHEN v.admissoes IS NULL AND v.desligamentos IS NULL THEN 'sem_observacao'
           WHEN v.saldo IS NULL THEN 'incompleto'
           ELSE 'completo'
       END AS situacao
FROM meses m
LEFT JOIN vw_movimentacao_mensal v
       ON v.data_referencia = m.data_referencia
      AND v.nivel_territorial = :nivel
      AND v.cod_territorio = :cod_territorio
      AND v.metodologia = :metodologia
      AND v.escopo_territorial = :escopo
ORDER BY m.data_referencia;

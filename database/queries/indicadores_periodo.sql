-- Resumo de um período para a UF: totais somados dos municípios e distribuição dos saldos.
-- Parâmetros: :uf, :metodologia, :inicio, :fim
WITH por_municipio AS (
    SELECT municipio_cod,
           sum(admissoes) AS admissoes,
           sum(desligamentos) AS desligamentos,
           sum(saldo) AS saldo
    FROM vw_movimentacao_mensal
    WHERE nivel_territorial = 'municipio'
      AND uf = :uf
      AND escopo_territorial = 'municipal'
      AND metodologia = :metodologia
      AND data_referencia BETWEEN :inicio AND :fim
    GROUP BY municipio_cod
)
-- sum(bigint) devolve numeric; o CAST mantém contagens como inteiros.
SELECT count(*) AS municipios_com_observacao,
       CAST(sum(admissoes) AS bigint) AS admissoes,
       CAST(sum(desligamentos) AS bigint) AS desligamentos,
       CAST(sum(saldo) AS bigint) AS saldo,
       count(*) FILTER (WHERE saldo > 0) AS municipios_saldo_positivo,
       count(*) FILTER (WHERE saldo < 0) AS municipios_saldo_negativo,
       count(*) FILTER (WHERE saldo = 0) AS municipios_saldo_zero
FROM por_municipio;

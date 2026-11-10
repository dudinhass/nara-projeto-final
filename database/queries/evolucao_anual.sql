-- Totais anuais de um território. ano_completo = 12 meses com admissões e desligamentos;
-- anos parciais (o ano corrente) ou com lacunas não devem ser comparados como completos.
-- Parâmetros: :nivel, :cod_territorio, :metodologia, :escopo
SELECT v.ano,
       sum(v.admissoes) AS admissoes,
       sum(v.desligamentos) AS desligamentos,
       sum(v.saldo) AS saldo,
       count(v.saldo) AS meses_com_saldo,
       count(v.saldo) = 12 AS ano_completo
FROM vw_movimentacao_mensal v
WHERE v.nivel_territorial = :nivel
  AND v.cod_territorio = :cod_territorio
  AND v.metodologia = :metodologia
  AND v.escopo_territorial = :escopo
GROUP BY v.ano
ORDER BY v.ano;

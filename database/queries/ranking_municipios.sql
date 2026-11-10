-- Ranking de municípios por {coluna} (admissoes | desligamentos | saldo) num período.
-- {coluna} e {ordem} são substituídos a partir de listas fechadas no código Python,
-- nunca a partir de texto livre.
-- Parâmetros: :uf, :metodologia, :inicio, :fim, :limite
WITH por_municipio AS (
    SELECT v.municipio_cod,
           sum(v.admissoes) AS admissoes,
           sum(v.desligamentos) AS desligamentos,
           sum(v.saldo) AS saldo,
           count(v.saldo) AS meses_com_saldo
    FROM vw_movimentacao_mensal v
    WHERE v.nivel_territorial = 'municipio'
      AND v.escopo_territorial = 'municipal'
      AND v.uf = :uf
      AND v.metodologia = :metodologia
      AND v.data_referencia BETWEEN :inicio AND :fim
    GROUP BY v.municipio_cod
)
SELECT rank() OVER (ORDER BY p.{coluna} {ordem}) AS posicao,
       m.cod_ibge,
       m.nome AS municipio,
       p.admissoes,
       p.desligamentos,
       p.saldo,
       p.meses_com_saldo
FROM por_municipio p
JOIN vw_municipios_validados m ON m.cod_ibge = p.municipio_cod
WHERE p.{coluna} IS NOT NULL
ORDER BY p.{coluna} {ordem}, m.nome
LIMIT :limite;

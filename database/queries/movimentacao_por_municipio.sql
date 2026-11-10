-- Totais por município num período (uma metodologia). Só municípios e observações validados no IpeaData. Municípios sem observação aparecem com
-- NULL (nunca zero). O saldo soma apenas meses em que admissões e desligamentos existem.
-- Parâmetros: :uf, :metodologia, :inicio, :fim, :codigos (array de códigos IBGE ou NULL = todos)
SELECT m.cod_ibge,
       m.nome AS municipio,
       sum(v.admissoes) AS admissoes,
       sum(v.desligamentos) AS desligamentos,
       sum(v.saldo) AS saldo,
       count(v.admissoes) AS meses_com_admissoes,
       count(v.desligamentos) AS meses_com_desligamentos,
       count(v.saldo) AS meses_com_saldo
FROM vw_municipios_validados m
LEFT JOIN vw_movimentacao_mensal v
       ON v.municipio_cod = m.cod_ibge
      AND v.nivel_territorial = 'municipio'
      AND v.escopo_territorial = 'municipal'
      AND v.metodologia = :metodologia
      AND v.data_referencia BETWEEN :inicio AND :fim
WHERE m.uf = :uf
  AND (CAST(:codigos AS text[]) IS NULL OR m.cod_ibge = ANY (CAST(:codigos AS text[])))
GROUP BY m.cod_ibge, m.nome
ORDER BY m.nome;

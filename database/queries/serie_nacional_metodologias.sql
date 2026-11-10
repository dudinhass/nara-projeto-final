-- Série nacional de um indicador em várias metodologias, em sequência, marcando a primeira
-- competência de cada metodologia (quebra metodológica). Não soma metodologias.
-- Parâmetros: :indicador, :metodologias (array)
SELECT r.data_referencia,
       s.metodologia,
       s.codigo AS serie,
       r.valor,
       r.data_referencia = min(r.data_referencia) OVER (PARTITION BY s.metodologia) AS inicio_da_metodologia
FROM vw_registros_validados r
JOIN series_indicadores s ON s.id = r.serie_id
WHERE s.escopo_territorial = 'nacional'
  AND s.indicador = :indicador
  AND s.metodologia = ANY (CAST(:metodologias AS text[]))
ORDER BY r.data_referencia, s.metodologia;

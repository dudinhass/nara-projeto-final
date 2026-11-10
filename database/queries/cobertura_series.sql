-- Primeira e última competência, observações e territórios por série e nível.
-- Considera somente observações com procedência validada no IpeaData.
SELECT s.codigo AS serie, s.indicador, s.metodologia, s.familia_metodologica, s.escopo_territorial,
       r.nivel_territorial,
       min(r.data_referencia) AS primeira_competencia,
       max(r.data_referencia) AS ultima_competencia,
       count(*) AS observacoes,
       count(DISTINCT r.cod_territorio) AS territorios
FROM vw_registros_validados r
JOIN series_indicadores s ON s.id = r.serie_id
GROUP BY s.codigo, s.indicador, s.metodologia, s.familia_metodologica, s.escopo_territorial, r.nivel_territorial
ORDER BY s.familia_metodologica, s.metodologia, s.codigo, r.nivel_territorial;

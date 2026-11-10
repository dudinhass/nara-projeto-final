# Relatório de validação — Etapa 1

Gerado automaticamente em 2026-10-26T13:14:37+00:00 por `python -m scripts.gerar_relatorio`. Não edite à mão.

## Resultado: **APROVADA**

Nenhum problema crítico.

## Integridade dos arquivos

29 arquivos processados conferidos por SHA-256 (manifesto `data/processed/manifesto.json`). Ausentes: 0; alterados: 0.

## Verificações por série

| Série | Observações | Período | Duplicadas | Nulos | Negativos | Datas inválidas | SHA-256 dos brutos | Outra UF | Fora da lista oficial |
|---|---|---|---|---|---|---|---|---|---|
| ADMISNC | 17.509 | 2020-01-01 a 2026-08-01 | 0 | 0 | 0 | 0 | ok | 0 | 0 |
| DESLIGNC | 17.509 | 2020-01-01 a 2026-08-01 | 0 | 0 | 0 | 0 | ok | 0 | 0 |
| CAGED12_ADMIS | 248 | 1999-05-01 a 2019-12-01 | 0 | 0 | 0 | 0 | ok | — | — |
| CAGED12_DESLIG | 247 | 1999-05-01 a 2019-12-01 | 0 | 0 | 0 | 0 | ok | — | — |
| CAGED12_SALDO12 | 248 | 1999-05-01 a 2019-12-01 | 0 | 0 | — | 0 | ok | — | — |
| CAGED12_ADMISN12 | 80 | 2020-01-01 a 2026-08-01 | 0 | 0 | 0 | 0 | ok | — | — |
| CAGED12_DESLIGN12 | 80 | 2020-01-01 a 2026-08-01 | 0 | 0 | 0 | 0 | ok | — | — |
| CAGED12_SALDON12 | 80 | 2020-01-01 a 2026-08-01 | 0 | 0 | — | 0 | ok | — | — |
| CAGED12_ADMISNAJU12 | 80 | 2020-01-01 a 2026-08-01 | 0 | 0 | 0 | 0 | ok | — | — |
| CAGED12_DESLIGNAJU12 | 80 | 2020-01-01 a 2026-08-01 | 0 | 0 | 0 | 0 | ok | — | — |
| CAGED12_SALDONAJU12 | 80 | 2020-01-01 a 2026-08-01 | 0 | 0 | — | 0 | ok | — | — |

## Consistência entre níveis e séries

Diferenças aqui são **documentadas, não corrigidas**: refletem a forma como a fonte publica.

| Comparação | Meses comparados | Meses divergentes | Maior diferença absoluta | Diferença média (%) |
|---|---|---|---|---|
| ADMISNC / soma_municipios_vs_total_uf | 80 | 0 | 0.0 | 0.0 |
| ADMISNC / brasil_base_regional_vs_serie_nacional | 80 | 2 | 3.0 | 0.0 |
| DESLIGNC / soma_municipios_vs_total_uf | 80 | 0 | 0.0 | 0.0 |
| DESLIGNC / brasil_base_regional_vs_serie_nacional | 80 | 0 | 0.0 | 0.0 |
| saldo_calculado_vs_publicado / novo_caged_sem_ajuste | 80 | 0 | 0.0 | 0.0 |
| saldo_calculado_vs_publicado / novo_caged_com_ajuste | 80 | 0 | 0.0 | 0.0 |
| saldo_calculado_vs_publicado / caged_tradicional | 247 | 3 | 36000.0 | 0.2596 |
| com_ajuste_vs_sem_ajuste_nacional / admissoes | 80 | 79 | 160786.0 | 3.0053 |
| com_ajuste_vs_sem_ajuste_nacional / desligamentos | 80 | 79 | 174365.0 | 3.7171 |

CAGED tradicional (1999-05-01 a 2019-12-01) e Novo Caged (2020-01-01 a 2026-08-01): 0 meses sobrepostos. Meses faltantes no CAGED tradicional: `CAGED12_ADMIS`: nenhum; `CAGED12_DESLIG`: 2000-02-01; `CAGED12_SALDO12`: nenhum.

## Painel município × mês

17360 linhas (esperadas 17360); duplicadas: 0. Situação das admissões: {'valor_encontrado': 14303, 'zero_encontrado': 3046, 'observacao_ausente': 11}. Situação dos desligamentos: {'valor_encontrado': 14396, 'zero_encontrado': 2953, 'observacao_ausente': 11}.

## Indicadores calculáveis

| Indicador | Calculável / observação |
|---|---|
| total_admissoes | True |
| total_desligamentos | True |
| saldo_empregos | True |
| evolucao_mensal | True |
| evolucao_anual | True |
| comparacao_municipios | True |
| ranking_municipios | True |
| taxas_percentuais | False |
| observacao_taxas | Não calculáveis: o IpeaData não oferece estoque de empregos formais por município compatível com o Novo Caged. Os totais são contagens absolutas e não devem ser apresentados como taxas. |

## Testes automatizados

Resultado de `pytest` lido de `data/reports/pytest.xml` (executado em 2026-10-26T10:10:33.323288-03:00): **238 testes, 0 falhas, 0 erros, 0 pulados** em 149.6 s.

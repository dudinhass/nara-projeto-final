# Cobertura histórica — admissões e desligamentos nos municípios do Maranhão

Gerado automaticamente em 2026-10-26T13:14:37+00:00 por `python -m scripts.gerar_relatorio` a partir de `data/checkpoints/`, `data/reports/` e `data/processed/`. Não edite à mão.

## Fontes efetivamente utilizadas

| Fonte | Papel | Referência |
|---|---|---|
| IpeaData (API OData v4) | Única fonte de obtenção: observações e cadastro de municípios | https://www.ipeadata.gov.br/api/odata4/ |
| MTE/Caged | Origem estatística informada nos metadados; **nunca acessada diretamente** | — |

Regra do projeto: todos os dados vêm do IpeaData. Nenhuma outra fonte é consultada pelo pipeline; a comprovação registro a registro está em [auditoria_origem_ipeadata.md](auditoria_origem_ipeadata.md).

## Séries e indicadores

| Série | Indicador | Metodologia | Cobertura territorial | Periodicidade | Unidade | Primeiro mês | Último mês | Meses | Situação na fonte |
|---|---|---|---|---|---|---|---|---|---|
| ADMISNC | admissoes | Novo Caged - sem ajuste | Municípios, UF e Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | não informado |
| DESLIGNC | desligamentos | Novo Caged - sem ajuste | Municípios, UF e Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | não informado |
| CAGED12_ADMIS | admissoes | CAGED tradicional | Somente Brasil | Mensal | Pessoa | 1999-05 | 2019-12 | 248 | inativa |
| CAGED12_DESLIG | desligamentos | CAGED tradicional | Somente Brasil | Mensal | Pessoa | 1999-05 | 2019-12 | 247 | inativa |
| CAGED12_SALDO12 | saldo | CAGED tradicional | Somente Brasil | Mensal | Pessoa | 1999-05 | 2019-12 | 248 | inativa |
| CAGED12_ADMISN12 | admissoes | Novo Caged - sem ajuste | Somente Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | ativa |
| CAGED12_DESLIGN12 | desligamentos | Novo Caged - sem ajuste | Somente Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | ativa |
| CAGED12_SALDON12 | saldo | Novo Caged - sem ajuste | Somente Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | ativa |
| CAGED12_ADMISNAJU12 | admissoes | Novo Caged - com ajuste | Somente Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | ativa |
| CAGED12_DESLIGNAJU12 | desligamentos | Novo Caged - com ajuste | Somente Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | ativa |
| CAGED12_SALDONAJU12 | saldo | Novo Caged - com ajuste | Somente Brasil | Mensal | Pessoa | 2020-01 | 2026-08 | 80 | ativa |

Somente `ADMISNC` e `DESLIGNC` têm nível municipal; são elas que formam o painel dos 217 municípios. As demais são totais nacionais, guardadas em `data/processed/referencia_nacional/` só como referência e **nunca** convertidas em dado municipal. CAGED tradicional e Novo Caged não são emendados: o primeiro termina em 2019-12 e o segundo começa em 2020-01.

## Registros coletados

"Lidos" são todos os registros da resposta da API (o Brasil inteiro, pois o servidor não filtra). "Válidos" são as observações aceitas para o Maranhão (municípios, total da UF e Brasil) ou, nas séries nacionais, para o Brasil. Registros de outras UFs, regiões e áreas metropolitanas são excluídos do escopo e não contam como rejeitados.

| Série | Lidos | Válidos | Rejeitados | Duplicatas exatas | Chaves conflitantes | Armazenadas |
|---|---|---|---|---|---|---|
| ADMISNC | 448.562 | 17.509 | 0 | 0 | 0 | 17.509 |
| DESLIGNC | 448.562 | 17.509 | 0 | 0 | 0 | 17.509 |
| CAGED12_ADMIS | 248 | 248 | 0 | 0 | 0 | 248 |
| CAGED12_DESLIG | 247 | 247 | 0 | 0 | 0 | 247 |
| CAGED12_SALDO12 | 248 | 248 | 0 | 0 | 0 | 248 |
| CAGED12_ADMISN12 | 80 | 80 | 0 | 0 | 0 | 80 |
| CAGED12_DESLIGN12 | 80 | 80 | 0 | 0 | 0 | 80 |
| CAGED12_SALDON12 | 80 | 80 | 0 | 0 | 0 | 80 |
| CAGED12_ADMISNAJU12 | 80 | 80 | 0 | 0 | 0 | 80 |
| CAGED12_DESLIGNAJU12 | 80 | 80 | 0 | 0 | 0 | 80 |
| CAGED12_SALDONAJU12 | 80 | 80 | 0 | 0 | 0 | 80 |
| **Total** | 898.347 | 36.241 | 0 | 0 | 0 | 36.241 |

## Cobertura territorial

- Cadastro de municípios (entidade `Territorios` do IpeaData): **217** municípios válidos de 217 registros; problemas na validação estrutural: nenhum.

| Indicador | Municípios com dados | Municípios sem dados | Quais |
|---|---|---|---|
| admissoes | 217 | 0 | nenhum |
| desligamentos | 217 | 0 | nenhum |

## Cobertura temporal

| Indicador | Primeiro mês | Último mês | Primeiro ano | Último ano | Anos com dados |
|---|---|---|---|---|---|
| admissoes | 2020-01-01 | 2026-08-01 | 2020 | 2026 | 7 |
| desligamentos | 2020-01-01 | 2026-08-01 | 2020 | 2026 | 7 |

A matriz anual avalia 1999–2026: do primeiro ano publicado por qualquer série da família CAGED no IpeaData (CAGED tradicional, só nacional) até o último ano disponível. Os anos anteriores à série municipal aparecem como `nao_disponibilizado_pela_fonte`.

### Situação por município × ano × indicador

| Indicador | completo | incompleto | nao_disponibilizado_pela_fonte |
|---|---|---|---|
| admissoes | 1.508 | 11 | 4.557 |
| desligamentos | 1.508 | 11 | 4.557 |

### Anos com disponibilidade municipal

| Ano | Indicador | Meses esperados | Municípios completos | Municípios incompletos | Municípios sem registros |
|---|---|---|---|---|---|
| 2020 | admissoes | 12 | 217 | 0 | 0 |
| 2020 | desligamentos | 12 | 217 | 0 | 0 |
| 2021 | admissoes | 12 | 217 | 0 | 0 |
| 2021 | desligamentos | 12 | 217 | 0 | 0 |
| 2022 | admissoes | 12 | 217 | 0 | 0 |
| 2022 | desligamentos | 12 | 217 | 0 | 0 |
| 2023 | admissoes | 12 | 217 | 0 | 0 |
| 2023 | desligamentos | 12 | 217 | 0 | 0 |
| 2024 | admissoes | 12 | 206 | 11 | 0 |
| 2024 | desligamentos | 12 | 206 | 11 | 0 |
| 2025 | admissoes | 12 | 217 | 0 | 0 |
| 2025 | desligamentos | 12 | 217 | 0 | 0 |
| 2026 | admissoes | 8 | 217 | 0 | 0 |
| 2026 | desligamentos | 8 | 217 | 0 | 0 |

## Lacunas temporais

Combinações município × mês dentro da disponibilidade da série, sem observação publicada. Não foram preenchidas. "Lacuna sistêmica" indica um mês em que a fonte publicou menos municípios (no país inteiro) que nos meses vizinhos, ou seja, uma falha da publicação e não do município.

| Indicador | Código IBGE | Município | Mês | Lacuna sistêmica da fonte |
|---|---|---|---|---|
| admissoes | 2101301 | Bacuri | 2024-01 | sim |
| admissoes | 2101731 | Belágua | 2024-01 | sim |
| admissoes | 2102150 | Brejo de Areia | 2024-01 | sim |
| admissoes | 2102408 | Cajapió | 2024-01 | sim |
| admissoes | 2103125 | Central do Maranhão | 2024-01 | sim |
| admissoes | 2103554 | Conceição do Lago-Açu | 2024-01 | sim |
| admissoes | 2103901 | Duque Bacelar | 2024-01 | sim |
| admissoes | 2106359 | Marajá do Sena | 2024-01 | sim |
| admissoes | 2106672 | Milagres do Maranhão | 2024-01 | sim |
| admissoes | 2108058 | Paulino Neves | 2024-01 | sim |
| admissoes | 2109056 | Porto Rico do Maranhão | 2024-01 | sim |
| desligamentos | 2101301 | Bacuri | 2024-01 | sim |
| desligamentos | 2101731 | Belágua | 2024-01 | sim |
| desligamentos | 2102150 | Brejo de Areia | 2024-01 | sim |
| desligamentos | 2102408 | Cajapió | 2024-01 | sim |
| desligamentos | 2103125 | Central do Maranhão | 2024-01 | sim |
| desligamentos | 2103554 | Conceição do Lago-Açu | 2024-01 | sim |
| desligamentos | 2103901 | Duque Bacelar | 2024-01 | sim |
| desligamentos | 2106359 | Marajá do Sena | 2024-01 | sim |
| desligamentos | 2106672 | Milagres do Maranhão | 2024-01 | sim |
| desligamentos | 2108058 | Paulino Neves | 2024-01 | sim |
| desligamentos | 2109056 | Porto Rico do Maranhão | 2024-01 | sim |

- `ADMISNC`: meses com lacuna sistêmica na fonte: 2024-01-01.

- `DESLIGNC`: meses com lacuna sistêmica na fonte: 2024-01-01.

Arquivos detalhados: `data/reports/cobertura_municipio_ano_indicador.csv` (município × ano × indicador) e `data/reports/cobertura_municipio_mes_indicador.csv` (município × mês × indicador, com o status de cada mês).

## Execuções de coleta

Cada linha é uma tentativa registrada. "Retomadas" conta quantas vezes a execução foi retomada a partir do checkpoint após uma interrupção, inclusive quedas abruptas do processo, que não deixam registro próprio.

| Execução | Modo | Status | Retomadas | Registrada em |
|---|---|---|---|---|
| full-20261025T171239Z | full | concluida | 0 | 2026-10-25T17:14:09+00:00 |
| incremental-20261025T171506Z | incremental | concluida | 1 | 2026-10-25T17:17:56+00:00 |
| incremental-20261025T171808Z | incremental | concluida | 0 | 2026-10-25T17:19:50+00:00 |
| full-20261025T172007Z | full | concluida | 2 | 2026-10-25T17:23:56+00:00 |
| incremental-20261025T213351Z | incremental | concluida | 0 | 2026-10-25T21:34:16+00:00 |
| incremental-20261026T033201Z | incremental | concluida | 0 | 2026-10-26T03:32:15+00:00 |

## Erros de coleta

Nenhuma falha registrada.

## Pendências

Nenhuma pendência de coleta: a última execução concluiu todas as tarefas.

Limitações da fonte (não são pendências de coleta): não há dados municipais antes de 2020-01 no IpeaData; não há estoque de empregos por município (taxas não calculáveis); as séries municipais são "sem ajuste".

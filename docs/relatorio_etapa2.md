# Relatório da Etapa 2 — PostgreSQL

Gerado automaticamente em 2026-10-26T13:14:37+00:00 por `python -m scripts.gerar_relatorio` a partir de `data/reports/` (verificação, reconciliação, importações e testes). Não edite à mão.

## Ambiente

| Item | Valor |
|---|---|
| Servidor | PostgreSQL 17.11 on x86_64-windows |
| Banco / usuário | emprego_maranhao / emprego |
| Fuso do servidor | UTC |
| Migração Alembic | 0002 (head: 0002) — atualizada |
| Docker (detectado agora) | Docker instalado, mas o daemon não está ativo: failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: O sistema não conse |

## Objetos do banco

| Tabela | Linhas |
|---|---|
| fontes_dados | 3 |
| municipios | 217 |
| series_indicadores | 11 |
| registros_emprego | 36.241 |
| revisoes_registros | 0 |
| execucoes_importacao | 3 |
| arquivos_importados | 25 |
| inconsistencias_dados | 0 |
| snapshots_origem | 12 |
| auditorias_procedencia | 1 |

Restrições: primary_key=11, unique=6, foreign_key=16, check=35. Índices: 33. Views: vw_registros_validados, vw_municipios_validados, vw_movimentacao_mensal.

| Tabela | Tamanho total | Índices |
|---|---|---|
| registros_emprego | 32 MB | 10 MB |
| municipios | 184 kB | 72 kB |
| snapshots_origem | 120 kB | 64 kB |
| series_indicadores | 104 kB | 48 kB |
| arquivos_importados | 64 kB | 48 kB |
| fontes_dados | 48 kB | 32 kB |
| execucoes_importacao | 48 kB | 32 kB |
| revisoes_registros | 32 kB | 24 kB |
| auditorias_procedencia | 32 kB | 16 kB |
| inconsistencias_dados | 32 kB | 24 kB |
| alembic_version | 24 kB | 16 kB |

## Importações executadas

| ID | Tipo | Status | Lidos | Válidos | Inseridos | Atualizados | Inalterados | Rejeitados | Ausentes na origem | Arquivos proc. | Arquivos ign. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | FULL | concluida | 36.241 | 36.241 | 36.241 | 0 | 0 | 0 | 0 | 25 | 0 |
| 2 | INCREMENTAL | concluida | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 25 |
| 3 | FULL | concluida | 36.241 | 36.241 | 0 | 0 | 36.241 | 0 | 0 | 25 | 0 |

Carga histórica (importação 1, FULL, 3.64 s): lidos 36241, válidos 36241, inseridos 36241, atualizados 0, rejeitados 0. Registros no banco após a carga: 36241.

Integridade: chaves naturais duplicadas = 0; municípios cadastrados = 217; séries sem observações = nenhuma; inconsistências registradas = nenhuma; revisões registradas = 0.

## Cobertura histórica por fonte, metodologia e indicador

| Série | Indicador | Metodologia | Escopo | Nível | Primeira | Última | Observações | Territórios |
|---|---|---|---|---|---|---|---|---|
| CAGED12_ADMIS | admissoes | CAGED tradicional | nacional | brasil | 1999-05-01 | 2019-12-01 | 248 | 1 |
| CAGED12_DESLIG | desligamentos | CAGED tradicional | nacional | brasil | 1999-05-01 | 2019-12-01 | 247 | 1 |
| CAGED12_SALDO12 | saldo | CAGED tradicional | nacional | brasil | 1999-05-01 | 2019-12-01 | 248 | 1 |
| CAGED12_ADMISNAJU12 | admissoes | Novo Caged - com ajuste | nacional | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| CAGED12_DESLIGNAJU12 | desligamentos | Novo Caged - com ajuste | nacional | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| CAGED12_SALDONAJU12 | saldo | Novo Caged - com ajuste | nacional | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| ADMISNC | admissoes | Novo Caged - sem ajuste | municipal | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| ADMISNC | admissoes | Novo Caged - sem ajuste | municipal | estado | 2020-01-01 | 2026-08-01 | 80 | 1 |
| ADMISNC | admissoes | Novo Caged - sem ajuste | municipal | municipio | 2020-01-01 | 2026-08-01 | 17.349 | 217 |
| CAGED12_ADMISN12 | admissoes | Novo Caged - sem ajuste | nacional | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| CAGED12_DESLIGN12 | desligamentos | Novo Caged - sem ajuste | nacional | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| CAGED12_SALDON12 | saldo | Novo Caged - sem ajuste | nacional | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| DESLIGNC | desligamentos | Novo Caged - sem ajuste | municipal | brasil | 2020-01-01 | 2026-08-01 | 80 | 1 |
| DESLIGNC | desligamentos | Novo Caged - sem ajuste | municipal | estado | 2020-01-01 | 2026-08-01 | 80 | 1 |
| DESLIGNC | desligamentos | Novo Caged - sem ajuste | municipal | municipio | 2020-01-01 | 2026-08-01 | 17.349 | 217 |

Os 217 municípios estão cadastrados. Há dados municipais **somente a partir de 2020-01** (Novo Caged no IpeaData); o CAGED tradicional existe apenas como total nacional (1999-05 a 2019-12) e não é emendado ao Novo Caged.

## Reconciliação (arquivos processados → PostgreSQL): **CONCILIADO**

| Medida | Origem | Banco |
|---|---|---|
| Linhas | 36.241 | 36.241 |
| Soma dos valores | 1.511.729.335 | 1.511.729.335 |
| Municípios cadastrados | 217 | 217 |

Grupos série × ano comparados por contagem, soma e MD5 do conteúdo: 119 (divergentes: 0). Chaves duplicadas no banco: 0.

| Série | Linhas origem | Linhas banco | Início | Fim | Grupos divergentes |
|---|---|---|---|---|---|
| ADMISNC | 17.509 | 17.509 | 2020-01-01 | 2026-08-01 | 0 |
| CAGED12_ADMIS | 248 | 248 | 1999-05-01 | 2019-12-01 | 0 |
| CAGED12_ADMISN12 | 80 | 80 | 2020-01-01 | 2026-08-01 | 0 |
| CAGED12_ADMISNAJU12 | 80 | 80 | 2020-01-01 | 2026-08-01 | 0 |
| CAGED12_DESLIG | 247 | 247 | 1999-05-01 | 2019-12-01 | 0 |
| CAGED12_DESLIGN12 | 80 | 80 | 2020-01-01 | 2026-08-01 | 0 |
| CAGED12_DESLIGNAJU12 | 80 | 80 | 2020-01-01 | 2026-08-01 | 0 |
| CAGED12_SALDO12 | 248 | 248 | 1999-05-01 | 2019-12-01 | 0 |
| CAGED12_SALDON12 | 80 | 80 | 2020-01-01 | 2026-08-01 | 0 |
| CAGED12_SALDONAJU12 | 80 | 80 | 2020-01-01 | 2026-08-01 | 0 |
| DESLIGNC | 17.509 | 17.509 | 2020-01-01 | 2026-08-01 | 0 |

| Ano | Linhas origem | Linhas banco |
|---|---|---|
| 1999 | 24 | 24 |
| 2000 | 35 | 35 |
| 2001 | 36 | 36 |
| 2002 | 36 | 36 |
| 2003 | 36 | 36 |
| 2004 | 36 | 36 |
| 2005 | 36 | 36 |
| 2006 | 36 | 36 |
| 2007 | 36 | 36 |
| 2008 | 36 | 36 |
| 2009 | 36 | 36 |
| 2010 | 36 | 36 |
| 2011 | 36 | 36 |
| 2012 | 36 | 36 |
| 2013 | 36 | 36 |
| 2014 | 36 | 36 |
| 2015 | 36 | 36 |
| 2016 | 36 | 36 |
| 2017 | 36 | 36 |
| 2018 | 36 | 36 |
| 2019 | 36 | 36 |
| 2020 | 5.328 | 5.328 |
| 2021 | 5.328 | 5.328 |
| 2022 | 5.328 | 5.328 |
| 2023 | 5.328 | 5.328 |
| 2024 | 5.306 | 5.306 |
| 2025 | 5.328 | 5.328 |
| 2026 | 3.552 | 3.552 |

- `ADMISNC`: 217 municípios com observações (11 municípios com 79 meses, 206 municípios com 80 meses). Os 11 municípios com 79 meses correspondem à lacuna da fonte em 2024-01 (documentada na etapa 1.5).

- `DESLIGNC`: 217 municípios com observações (11 municípios com 79 meses, 206 municípios com 80 meses). Os 11 municípios com 79 meses correspondem à lacuna da fonte em 2024-01 (documentada na etapa 1.5).

## Resultados das consultas (metodologia Novo Caged - sem ajuste; ano completo mais recente: 2025)

Última competência disponível: 2026-08-01.

Totais do Maranhão em 2025: admissões 282058, desligamentos 254134, saldo 27924 (total oficial da UF); soma dos municípios: admissões 282058, desligamentos 254134.

### Maiores saldos

| Posição | Município | Admissões | Desligamentos | Saldo |
|---|---|---|---|---|
| 1 | São Luís | 131.263 | 114.102 | 17.161 |
| 2 | Imperatriz | 29.044 | 27.892 | 1.152 |
| 3 | Timon | 6.811 | 5.899 | 912 |
| 4 | Balsas | 15.422 | 14.630 | 792 |
| 5 | Bacabal | 4.545 | 3.858 | 687 |
| 6 | Barra do Corda | 2.178 | 1.704 | 474 |
| 7 | Santa Inês | 3.812 | 3.354 | 458 |
| 8 | Santa Luzia do Paruá | 1.188 | 778 | 410 |
| 9 | Colinas | 1.447 | 1.054 | 393 |
| 10 | Porto Franco | 1.468 | 1.109 | 359 |

### Menores saldos

| Posição | Município | Admissões | Desligamentos | Saldo |
|---|---|---|---|---|
| 1 | Açailândia | 9.345 | 9.899 | -554 |
| 2 | Governador Edison Lobão | 985 | 1.281 | -296 |
| 3 | Aldeias Altas | 1.181 | 1.362 | -181 |
| 4 | Bom Jesus das Selvas | 454 | 560 | -106 |
| 5 | Itinga do Maranhão | 962 | 1.067 | -105 |

### Evolução anual do Maranhão (total oficial da UF)

| Ano | Admissões | Desligamentos | Saldo | Meses | Ano completo |
|---|---|---|---|---|---|
| 2020 | 147.185 | 127.161 | 20.024 | 12 | sim |
| 2021 | 197.238 | 157.919 | 39.319 | 12 | sim |
| 2022 | 246.172 | 207.879 | 38.293 | 12 | sim |
| 2023 | 242.242 | 220.321 | 21.921 | 12 | sim |
| 2024 | 259.585 | 243.275 | 16.310 | 12 | sim |
| 2025 | 282.058 | 254.134 | 27.924 | 12 | sim |
| 2026 | 196.998 | 178.991 | 18.007 | 8 | não |

Indicadores do período 2025: 153 municípios com saldo positivo, 62 negativo e 2 zero.

## Desempenho (EXPLAIN ANALYZE)

| Consulta | Tempo (ms) | Índices usados | Varredura sequencial em |
|---|---|---|---|
| ranking de municípios por saldo (2025) | 31.029 | ix_registros_emprego_serie_nivel_data, pk_snapshots_origem, uq_series_indicadores_fonte_indicador_metodologia_escopo | fontes_dados, municipios, series_indicadores, snapshots_origem |
| totais por município (todos, 1 ano) | 29.618 | ix_registros_emprego_serie_nivel_data, pk_snapshots_origem, uq_series_indicadores_fonte_indicador_metodologia_escopo | fontes_dados, municipios, series_indicadores, snapshots_origem |
| evolução mensal da capital (histórico completo) | 1.368 | pk_series_indicadores, pk_snapshots_origem, uq_registros_emprego_chave_natural | fontes_dados, municipios, series_indicadores |
| totais da UF (2025) | 24.461 | ix_registros_emprego_serie_nivel_data, uq_registros_emprego_chave_natural, uq_series_indicadores_fonte_indicador_metodologia_escopo | fontes_dados, municipios, series_indicadores, snapshots_origem |
| observações de um município numa série (tabela de fatos) | 0.105 | ix_registros_emprego_municipio_serie_data | — |

A tabela de fatos é sempre acessada por índice; varreduras sequenciais ocorrem só nas dimensões pequenas (séries e municípios), onde são a escolha correta. Com tempos dessa ordem e 36241 observações, **não há necessidade técnica** de materialized views nem de particionamento (que só compensa a partir de dezenas de milhões de linhas). Planos completos em `data/reports/verificacao_banco.json`.

## Testes automatizados

`pytest` (2026-10-26T10:10:33.323288-03:00): **238 testes, 0 falhas, 0 erros, 0 pulados** em 149.6 s.

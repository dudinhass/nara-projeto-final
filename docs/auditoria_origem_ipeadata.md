# Auditoria de procedência — uso exclusivo de dados do IpeaData

Gerado automaticamente em 2026-10-26T13:14:39+00:00 por `python -m scripts.gerar_relatorio`, a partir do PostgreSQL e de `data/reports/auditoria_procedencia.json`. Não edite à mão.

**Regra do projeto:** todos os dados devem estar disponíveis no IpeaData (<https://www.ipeadata.gov.br/>). Ser originalmente do CAGED/Novo CAGED é permitido **desde que o IpeaData os publique**; obter dados direto do Ministério do Trabalho, do IBGE ou de qualquer outro portal é proibido.

Auditoria **1** — CONCLUIDA — iniciada em 2026-10-26T03:33:20+00:00, duração 88.0 s.

## 1. Resultado em uma tabela

| Classificação | Registros | Parcela |
|---|---|---|
| VALIDADO — IPEADATA | 36.241 | 100.0% |
| NÃO VALIDADO | 0 | 0.0% |
| INCOMPATÍVEL | 0 | 0.0% |
| **Total no banco** | 36.241 | 100% |

- **Validado — IpeaData:** procedência e valores comprovados contra a resposta oficial do IpeaData. É o **único** grupo que as consultas analíticas enxergam.

- **Não validado:** origem ainda não comprovada (não é prova de erro). Fica no banco, fora das consultas.

- **Incompatível:** comprovadamente de fonte não autorizada. Fica no banco, isolado das consultas.

Nada foi apagado: a classificação é um atributo (`registros_emprego.status_procedencia`) e as views `vw_*_validados` filtram. Reverter é só atualizar o atributo.

## 2. Série × período × nível territorial

| Série | Período | Nível territorial | Registros | Procedência (URL · arquivo bruto · hash) | Situação |
|---|---|---|---|---|---|
| `ADMISNC` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')` · `data/raw/ipeadata/ADMISNC/ADMISNC_20261025T172239Z.json.gz` · sha256 `c700d925ab46…` | VALIDADO — IPEADATA |
| `ADMISNC` | 2020-01 a 2026-08 | estado (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')` · `data/raw/ipeadata/ADMISNC/ADMISNC_20261025T172239Z.json.gz` · sha256 `c700d925ab46…` | VALIDADO — IPEADATA |
| `ADMISNC` | 2020-01 a 2026-08 | municipio (217 territ.) | 17.349 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADMISNC')` · `data/raw/ipeadata/ADMISNC/ADMISNC_20261025T172239Z.json.gz` · sha256 `c700d925ab46…` | VALIDADO — IPEADATA |
| `CAGED12_ADMIS` | 1999-05 a 2019-12 | brasil (1 territ.) | 248 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_ADMIS')` · `data/raw/ipeadata/CAGED12_ADMIS/CAGED12_ADMIS_20261025T172340Z.json.gz` · sha256 `139c23188f05…` | VALIDADO — IPEADATA |
| `CAGED12_ADMISN12` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_ADMISN12')` · `data/raw/ipeadata/CAGED12_ADMISN12/CAGED12_ADMISN12_20261025T172342Z.json.gz` · sha256 `a143677ecaa7…` | VALIDADO — IPEADATA |
| `CAGED12_ADMISNAJU12` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_ADMISNAJU12')` · `data/raw/ipeadata/CAGED12_ADMISNAJU12/CAGED12_ADMISNAJU12_20261025T172345Z.json.gz` · sha256 `aa990528f1dc…` | VALIDADO — IPEADATA |
| `CAGED12_DESLIG` | 1999-05 a 2019-12 | brasil (1 territ.) | 247 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_DESLIG')` · `data/raw/ipeadata/CAGED12_DESLIG/CAGED12_DESLIG_20261025T172340Z.json.gz` · sha256 `69fb1006dd68…` | VALIDADO — IPEADATA |
| `CAGED12_DESLIGN12` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_DESLIGN12')` · `data/raw/ipeadata/CAGED12_DESLIGN12/CAGED12_DESLIGN12_20261025T172343Z.json.gz` · sha256 `2d18b4243637…` | VALIDADO — IPEADATA |
| `CAGED12_DESLIGNAJU12` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_DESLIGNAJU12')` · `data/raw/ipeadata/CAGED12_DESLIGNAJU12/CAGED12_DESLIGNAJU12_20261025T172346Z.json.gz` · sha256 `2219af1e2c17…` | VALIDADO — IPEADATA |
| `CAGED12_SALDO12` | 1999-05 a 2019-12 | brasil (1 territ.) | 248 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_SALDO12')` · `data/raw/ipeadata/CAGED12_SALDO12/CAGED12_SALDO12_20261025T172341Z.json.gz` · sha256 `349128db30fe…` | VALIDADO — IPEADATA |
| `CAGED12_SALDON12` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_SALDON12')` · `data/raw/ipeadata/CAGED12_SALDON12/CAGED12_SALDON12_20261025T172344Z.json.gz` · sha256 `939d39523544…` | VALIDADO — IPEADATA |
| `CAGED12_SALDONAJU12` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='CAGED12_SALDONAJU12')` · `data/raw/ipeadata/CAGED12_SALDONAJU12/CAGED12_SALDONAJU12_20261025T172347Z.json.gz` · sha256 `e3c04c89641d…` | VALIDADO — IPEADATA |
| `DESLIGNC` | 2020-01 a 2026-08 | brasil (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='DESLIGNC')` · `data/raw/ipeadata/DESLIGNC/DESLIGNC_20261025T172310Z.json.gz` · sha256 `fb850523feab…` | VALIDADO — IPEADATA |
| `DESLIGNC` | 2020-01 a 2026-08 | estado (1 territ.) | 80 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='DESLIGNC')` · `data/raw/ipeadata/DESLIGNC/DESLIGNC_20261025T172310Z.json.gz` · sha256 `fb850523feab…` | VALIDADO — IPEADATA |
| `DESLIGNC` | 2020-01 a 2026-08 | municipio (217 territ.) | 17.349 | `https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='DESLIGNC')` · `data/raw/ipeadata/DESLIGNC/DESLIGNC_20261025T172310Z.json.gz` · sha256 `fb850523feab…` | VALIDADO — IPEADATA |

## 3. Séries disponíveis no IpeaData (metadados consultados na auditoria)

| Série | Nome | Base | Periodicidade | Unidade | Fonte original declarada | Escopo configurado | Atualizada em | Auditoria |
|---|---|---|---|---|---|---|---|---|
| `ADMISNC` | Empregados - admissões - Novo Caged sem ajuste | Regional | Mensal | Pessoa | MTE/Caged | municipal | 2026-10-05 | concluida |
| `DESLIGNC` | Empregados - demissões - Novo Caged sem ajuste | Regional | Mensal | Pessoa | MTE/Caged | municipal | 2026-10-05 | concluida |
| `CAGED12_ADMIS` | Empregados - admissões - INATIVA | Macroeconômico | Mensal | Pessoa | MTE/Caged | nacional | 2020-05-27 | concluida |
| `CAGED12_DESLIG` | Empregados - demissões - INATIVA | Macroeconômico | Mensal | Pessoa | MTE/Caged | nacional | 2020-05-27 | concluida |
| `CAGED12_SALDO12` | Empregados - saldo - INATIVA | Macroeconômico | Mensal | Pessoa | MTE/Caged | nacional | 2020-05-27 | concluida |
| `CAGED12_ADMISN12` | Empregados - admissões - sem ajuste - novo Caged | Macroeconômico | Mensal | Pessoa | Min. Economia/SEPRT/Novo Caged | nacional | 2026-09-30 | concluida |
| `CAGED12_DESLIGN12` | Empregados - demissões - sem ajuste - novo Caged | Macroeconômico | Mensal | Pessoa | Min. Economia/SEPRT/Novo Caged | nacional | 2026-09-30 | concluida |
| `CAGED12_SALDON12` | Empregados - saldo - sem ajuste - novo Caged | Macroeconômico | Mensal | Pessoa | Min. Economia/SEPRT/Novo Caged | nacional | 2026-09-30 | concluida |
| `CAGED12_ADMISNAJU12` | Empregados - admissões - com ajuste - novo Caged | Macroeconômico | Mensal | Pessoa | Min. Economia/SEPRT/Novo Caged | nacional | 2026-09-30 | concluida |
| `CAGED12_DESLIGNAJU12` | Empregados - demissões - com ajuste - novo Caged | Macroeconômico | Mensal | Pessoa | Min. Economia/SEPRT/Novo Caged | nacional | 2026-09-30 | concluida |
| `CAGED12_SALDONAJU12` | Empregados - saldo - com ajuste - novo Caged | Macroeconômico | Mensal | Pessoa | Min. Economia/SEPRT/Novo Caged | nacional | 2026-09-30 | concluida |

A coluna *Fonte original declarada* é um atributo descritivo informado pelo próprio IpeaData; o projeto **nunca** acessa essa fonte.

As séries `ADMIS` e `DESLIG` (do enunciado inicial) **não existem** no IpeaData e nunca foram utilizadas.

## 4. Cobertura municipal efetivamente confirmada

| Série | Municípios com observações validadas | Período validado |
|---|---|---|
| `ADMISNC` | 217 | 2020-01 a 2026-08 |
| `DESLIGNC` | 217 | 2020-01 a 2026-08 |

Cadastro de municípios (entidade `Territorios` do IpeaData): 217 validados.

**Somente `ADMISNC` e `DESLIGNC` têm nível municipal** no IpeaData. As outras nove séries são totais nacionais e são tratadas como tal: o banco impede que uma observação nacional ou estadual ocupe o nível municipal, e o pipeline rejeita níveis territoriais inesperados em séries nacionais.

## 5. Períodos com dados válidos e lacunas

| Série municipal | Primeiro mês validado | Último mês validado |
|---|---|---|
| `ADMISNC` | 2020-01 | 2026-08 |
| `DESLIGNC` | 2020-01 | 2026-08 |

- Antes de 2020-01 **não há dados municipais** no IpeaData; o CAGED tradicional existe só como total nacional (1999-05 a 2019-12) e não é emendado ao Novo Caged.

- Lacunas município × mês dentro do período (a fonte não publicou; **não foram preenchidas**):

| Indicador | Combinações ausentes | Municípios (mês) |
|---|---|---|
| admissoes | 11 | Bacuri (2024-01), Belágua (2024-01), Brejo de Areia (2024-01), Cajapió (2024-01), Central do Maranhão (2024-01), Conceição do Lago-Açu (2024-01), Duque Bacelar (2024-01), Marajá do Sena (2024-01), Milagres do Maranhão (2024-01), Paulino Neves (2024-01), Porto Rico do Maranhão (2024-01) |
| desligamentos | 11 | Bacuri (2024-01), Belágua (2024-01), Brejo de Areia (2024-01), Cajapió (2024-01), Central do Maranhão (2024-01), Conceição do Lago-Açu (2024-01), Duque Bacelar (2024-01), Marajá do Sena (2024-01), Milagres do Maranhão (2024-01), Paulino Neves (2024-01), Porto Rico do Maranhão (2024-01) |

## 6. Evidências das requisições ao IpeaData

24 requisições feitas pela auditoria, todas a `www.ipeadata.gov.br`:

| Consulta | HTTP | Bytes | SHA-256 do corpo | Consultado em (UTC) | Duração (s) |
|---|---|---|---|---|---|
| Territorios - municípios da UF | 200 | 39.011 | `8f72332d4a565164…` | 2026-10-26T03:33:21+00:00 | 1.0 |
| Territorios - UF | 200 | 275 | `84574ffc4204ca16…` | 2026-10-26T03:33:21+00:00 | 0.531 |
| Metadados('ADMISNC') | 200 | 1.636 | `8bd099527477230e…` | 2026-10-26T03:33:22+00:00 | 0.047 |
| ValoresSerie('ADMISNC') | 200 | 63.685.038 | `1a8c5ee61dc700f5…` | 2026-10-26T03:33:46+00:00 | 23.078 |
| Metadados('DESLIGNC') | 200 | 1.633 | `bd4af4895d1d22bd…` | 2026-10-26T03:33:56+00:00 | 0.718 |
| ValoresSerie('DESLIGNC') | 200 | 64.121.444 | `e8a8844debb324ec…` | 2026-10-26T03:34:21+00:00 | 24.843 |
| Metadados('CAGED12_ADMIS') | 200 | 744 | `ecf1338a81c485aa…` | 2026-10-26T03:34:31+00:00 | 0.594 |
| ValoresSerie('CAGED12_ADMIS') | 200 | 32.545 | `139c23188f05ea26…` | 2026-10-26T03:34:32+00:00 | 0.25 |
| Metadados('CAGED12_DESLIG') | 200 | 739 | `2c56c1a6b5e1e464…` | 2026-10-26T03:34:32+00:00 | 0.062 |
| ValoresSerie('CAGED12_DESLIG') | 200 | 32.651 | `69fb1006dd680e8f…` | 2026-10-26T03:34:34+00:00 | 0.219 |
| Metadados('CAGED12_SALDO12') | 200 | 767 | `028536164c169152…` | 2026-10-26T03:34:34+00:00 | 0.047 |
| ValoresSerie('CAGED12_SALDO12') | 200 | 32.811 | `349128db30fe1cb1…` | 2026-10-26T03:34:36+00:00 | 0.219 |
| Metadados('CAGED12_ADMISN12') | 200 | 1.507 | `347d7359a3e51c45…` | 2026-10-26T03:34:36+00:00 | 0.078 |
| ValoresSerie('CAGED12_ADMISN12') | 200 | 10.852 | `a143677ecaa732e1…` | 2026-10-26T03:34:38+00:00 | 0.203 |
| Metadados('CAGED12_DESLIGN12') | 200 | 1.506 | `b5d87eeecbfd8a87…` | 2026-10-26T03:34:38+00:00 | 0.046 |
| ValoresSerie('CAGED12_DESLIGN12') | 200 | 10.933 | `2d18b42436372f5f…` | 2026-10-26T03:34:40+00:00 | 0.203 |
| Metadados('CAGED12_SALDON12') | 200 | 1.545 | `37d429f0acd4500c…` | 2026-10-26T03:34:40+00:00 | 0.046 |
| ValoresSerie('CAGED12_SALDON12') | 200 | 10.775 | `939d39523544b833…` | 2026-10-26T03:34:42+00:00 | 0.218 |
| Metadados('CAGED12_ADMISNAJU12') | 200 | 1.603 | `b72874eb19652a21…` | 2026-10-26T03:34:42+00:00 | 0.062 |
| ValoresSerie('CAGED12_ADMISNAJU12') | 200 | 11.092 | `aa990528f1dcf66f…` | 2026-10-26T03:34:44+00:00 | 0.218 |
| Metadados('CAGED12_DESLIGNAJU12') | 200 | 1.605 | `b1059391d748c727…` | 2026-10-26T03:34:44+00:00 | 0.109 |
| ValoresSerie('CAGED12_DESLIGNAJU12') | 200 | 11.175 | `2219af1e2c178d9c…` | 2026-10-26T03:34:46+00:00 | 0.218 |
| Metadados('CAGED12_SALDONAJU12') | 200 | 1.660 | `978d6904e37d4e52…` | 2026-10-26T03:34:46+00:00 | 0.046 |
| ValoresSerie('CAGED12_SALDONAJU12') | 200 | 11.015 | `e3c04c89641d9a90…` | 2026-10-26T03:34:48+00:00 | 0.234 |

URLs completas e demais campos em `data/reports/auditoria_procedencia.json`.

## 7. Comparações realizadas

| Série | Registros na resposta oficial | Observações no escopo (MA/UF/Brasil) | Registros no banco | Iguais ao IpeaData | Valor diferente | Só no banco | Só no IpeaData | Iguais ao arquivo bruto | Corpo da resposta idêntico ao bruto (SHA-256) | Validados |
|---|---|---|---|---|---|---|---|---|---|---|
| `ADMISNC` | 448.562 | 17.509 | 17.509 | 17.509 | 0 | 0 | 0 | 17.509 | não (ver nota) | 17.509 |
| `DESLIGNC` | 448.562 | 17.509 | 17.509 | 17.509 | 0 | 0 | 0 | 17.509 | não (ver nota) | 17.509 |
| `CAGED12_ADMIS` | 248 | 248 | 248 | 248 | 0 | 0 | 0 | 248 | sim | 248 |
| `CAGED12_DESLIG` | 247 | 247 | 247 | 247 | 0 | 0 | 0 | 247 | sim | 247 |
| `CAGED12_SALDO12` | 248 | 248 | 248 | 248 | 0 | 0 | 0 | 248 | sim | 248 |
| `CAGED12_ADMISN12` | 80 | 80 | 80 | 80 | 0 | 0 | 0 | 80 | sim | 80 |
| `CAGED12_DESLIGN12` | 80 | 80 | 80 | 80 | 0 | 0 | 0 | 80 | sim | 80 |
| `CAGED12_SALDON12` | 80 | 80 | 80 | 80 | 0 | 0 | 0 | 80 | sim | 80 |
| `CAGED12_ADMISNAJU12` | 80 | 80 | 80 | 80 | 0 | 0 | 0 | 80 | sim | 80 |
| `CAGED12_DESLIGNAJU12` | 80 | 80 | 80 | 80 | 0 | 0 | 0 | 80 | sim | 80 |
| `CAGED12_SALDONAJU12` | 80 | 80 | 80 | 80 | 0 | 0 | 0 | 80 | sim | 80 |

Cada observação do banco é comparada, por nível territorial × território × mês, com (a) o arquivo bruto preservado (prova que nada mudou depois da coleta) e (b) a resposta oficial baixada de novo na auditoria. "Só no IpeaData" são meses publicados depois da coleta (aguardam a próxima coleta incremental).

**Nota sobre o SHA-256:** nas séries nacionais o corpo da resposta é byte a byte idêntico ao arquivo bruto guardado. Em `ADMISNC` e `DESLIGNC` o hash difere, porque a API devolve os 448.562 registros em ordem não determinística. Por isso a validação **não** se apoia no hash do corpo, e sim na comparação registro a registro (nível × território × mês × valor), que é independente da ordem. O hash do arquivo guardado continua sendo usado para provar que **ele** não foi alterado depois da coleta.

### Amostras lidas diretamente dos campos brutos da resposta oficial (83 comparadas, 0 divergentes)

| Série | Nível | Território | Competência | Valor na resposta oficial | Valor no banco | Situação |
|---|---|---|---|---|---|---|
| `ADMISNC` | municipio | 2111300 | 2020-01-01 | 5019.0 | 5.019 | igual |
| `ADMISNC` | municipio | 2111300 | 2023-06-01 | 9668.0 | 9.668 | igual |
| `ADMISNC` | municipio | 2111300 | 2026-08-01 | 10967.0 | 10.967 | igual |
| `ADMISNC` | municipio | 2105302 | 2020-01-01 | 1437.0 | 1.437 | igual |
| `ADMISNC` | municipio | 2105302 | 2023-06-01 | 2515.0 | 2.515 | igual |
| `ADMISNC` | municipio | 2105302 | 2026-08-01 | 2493.0 | 2.493 | igual |
| `ADMISNC` | municipio | 2103000 | 2020-01-01 | 153.0 | 153 | igual |
| `ADMISNC` | municipio | 2103000 | 2023-06-01 | 349.0 | 349 | igual |
| `DESLIGNC` | municipio | 2111300 | 2020-01-01 | 5426.0 | 5.426 | igual |
| `DESLIGNC` | municipio | 2111300 | 2023-06-01 | 8711.0 | 8.711 | igual |
| `DESLIGNC` | municipio | 2111300 | 2026-08-01 | 9996.0 | 9.996 | igual |
| `DESLIGNC` | municipio | 2105302 | 2020-01-01 | 1489.0 | 1.489 | igual |
| `DESLIGNC` | municipio | 2105302 | 2023-06-01 | 2094.0 | 2.094 | igual |
| `DESLIGNC` | municipio | 2105302 | 2026-08-01 | 2687.0 | 2.687 | igual |
| `DESLIGNC` | municipio | 2103000 | 2020-01-01 | 263.0 | 263 | igual |
| `DESLIGNC` | municipio | 2103000 | 2023-06-01 | 203.0 | 203 | igual |
| `CAGED12_ADMIS` | brasil | BR | 1999-05-01 | 732704.0 | 732.704 | igual |
| `CAGED12_ADMIS` | brasil | BR | 2009-06-01 | 1356349.0 | 1.356.349 | igual |
| `CAGED12_ADMIS` | brasil | BR | 2019-12-01 | 990848.0 | 990.848 | igual |
| `CAGED12_DESLIG` | brasil | BR | 1999-05-01 | 635522.0 | 635.522 | igual |
| `CAGED12_DESLIG` | brasil | BR | 2009-06-01 | 1236854.0 | 1.236.854 | igual |
| `CAGED12_DESLIG` | brasil | BR | 2019-12-01 | 1298159.0 | 1.298.159 | igual |
| `CAGED12_SALDO12` | brasil | BR | 1999-05-01 | 97182.0 | 97.182 | igual |
| `CAGED12_SALDO12` | brasil | BR | 2009-06-01 | 119495.0 | 119.495 | igual |
| `CAGED12_SALDO12` | brasil | BR | 2019-12-01 | -307311.0 | -307.311 | igual |
| `CAGED12_ADMISN12` | brasil | BR | 2020-01-01 | 1384986.0 | 1.384.986 | igual |
| `CAGED12_ADMISN12` | brasil | BR | 2023-06-01 | 1914130.0 | 1.914.130 | igual |
| `CAGED12_ADMISN12` | brasil | BR | 2026-08-01 | 2294563.0 | 2.294.563 | igual |
| `CAGED12_DESLIGN12` | brasil | BR | 2020-01-01 | 1292308.0 | 1.292.308 | igual |
| `CAGED12_DESLIGN12` | brasil | BR | 2023-06-01 | 1756932.0 | 1.756.932 | igual |
| `CAGED12_DESLIGN12` | brasil | BR | 2026-08-01 | 2128736.0 | 2.128.736 | igual |
| `CAGED12_SALDON12` | brasil | BR | 2020-01-01 | 92678.0 | 92.678 | igual |
| `CAGED12_SALDON12` | brasil | BR | 2023-06-01 | 157198.0 | 157.198 | igual |
| `CAGED12_SALDON12` | brasil | BR | 2026-08-01 | 165827.0 | 165.827 | igual |
| `CAGED12_ADMISNAJU12` | brasil | BR | 2020-01-01 | 1510012.0 | 1.510.012 | igual |
| `CAGED12_ADMISNAJU12` | brasil | BR | 2023-06-01 | 1937169.0 | 1.937.169 | igual |
| `CAGED12_ADMISNAJU12` | brasil | BR | 2026-08-01 | 2294563.0 | 2.294.563 | igual |
| `CAGED12_DESLIGNAJU12` | brasil | BR | 2020-01-01 | 1397925.0 | 1.397.925 | igual |
| `CAGED12_DESLIGNAJU12` | brasil | BR | 2023-06-01 | 1781338.0 | 1.781.338 | igual |
| `CAGED12_DESLIGNAJU12` | brasil | BR | 2026-08-01 | 2128736.0 | 2.128.736 | igual |
| `CAGED12_SALDONAJU12` | brasil | BR | 2020-01-01 | 112087.0 | 112.087 | igual |
| `CAGED12_SALDONAJU12` | brasil | BR | 2023-06-01 | 155831.0 | 155.831 | igual |
| `CAGED12_SALDONAJU12` | brasil | BR | 2026-08-01 | 165827.0 | 165.827 | igual |

`ausente_nos_dois` documenta, por exemplo, os municípios sem registro em 2024-01: nem o IpeaData nem o banco têm o dado.

## 8. Registros não validados e motivos

Nenhum registro ficou sem validação.

## 9. Alterações realizadas no pipeline de coleta

- **Cadastro de municípios passou a vir só do IpeaData** (entidade `Territorios`). Antes, o pipeline consultava a API de localidades do **IBGE** a cada coleta para obter a lista oficial — uso de fonte não autorizada, removido. A validação agora é estrutural (códigos de 7 dígitos da UF, sem repetição, nomes preenchidos, total esperado de 217).
- `IpeaClient` recusa qualquer endereço que não seja `https://www.ipeadata.gov.br/` — URL base, links de paginação (`@odata.nextLink`) e endereço final de cada resposta. Redirecionamentos **não** são seguidos.
- Cada série precisa passar nos metadados do IpeaData (código, numérica, base Regional/Macroeconômico, periodicidade mensal, unidade Pessoa) antes de ser baixada; série inexistente ou divergente é rejeitada sem download.
- Cada observação precisa carregar o código da série consultada (`SERCODIGO`); outra série é rejeitada.
- Séries nacionais só aceitam o nível Brasil: linhas municipais ou estaduais nelas são rejeitadas, nunca reclassificadas.
- `fontes.csv` lista só o IpeaData como fonte autorizada; MTE/Caged é registrado como origem estatística (não acessada).
- Lista fechada de séries (`CODIGOS_SERIES_AUTORIZADAS`); o importador recusa série ou arquivo de origem fora dela.
- Teste estático varre o código atrás de qualquer endereço que não seja do IpeaData.
- Os modos FULL e INCREMENTAL continuam abrangendo todos os períodos que o IpeaData disponibiliza; nada é estimado.

## 10. Alterações realizadas no PostgreSQL (migração `0002`)

- `fontes_dados`: `tipo_fonte` e `autorizada_para_coleta`. Só o IpeaData é autorizado; o IBGE ficou como `legado_nao_autorizado`.
- `snapshots_origem` (nova): por arquivo bruto — URL, status HTTP, SHA-256, horário, resultado e evidência da verificação.
- `auditorias_procedencia` (nova): cada execução da auditoria.
- `registros_emprego`, `series_indicadores`, `municipios`: `status_procedencia` (`validado_ipeadata` / `nao_validado` / `incompativel`), ligação ao snapshot e data da verificação. Tudo que já existia passou a `nao_validado` até a auditoria comprovar.
- Restrições: `CHECK` impede `validado_ipeadata` sem snapshot e data; URL do snapshot tem de ser do IpeaData; só fonte de acesso pode ser autorizada.
- Gatilhos: série ou município de fonte não autorizada é recusado; observação não pode apontar para snapshot de outra série.
- Views `vw_registros_validados`, `vw_municipios_validados` e `vw_movimentacao_mensal`: **só dados validados**. Todas as consultas analíticas passaram a ler apenas essas views.
- Reimportar um valor revisado revoga a validação daquele registro (volta a `nao_validado`) até nova auditoria.
- Migração testada com dados: aplicar, reverter e reaplicar preservam as linhas. Backup do banco feito antes da migração.

## 11. Resultados dos testes

`pytest` (2026-10-26T10:10:33.323288-03:00): **238 testes, 0 falhas, 0 erros, 0 pulados** em 149.6 s.

## 12. Verificação independente (executada manualmente em 26/10/2026)

Feita por scripts **sem nenhum import do projeto** (`scripts/independentes/`), que baixam cada série direto do IpeaData e comparam cada valor com o banco por SQL puro. Saídas reais, sem edição:

```text
ADMISNC: resposta=448562 registros, sha256=183ba8693a715c56…, no escopo=17509, banco=17509, iguais=17509, diferentes=0, só no banco=0, só na fonte=0
DESLIGNC: resposta=448562 registros, sha256=63e3daf7c965d686…, no escopo=17509, banco=17509, iguais=17509, diferentes=0, só no banco=0, só na fonte=0
CAGED12_ADMIS: resposta=248 registros, sha256=139c23188f05ea26…, no escopo=248, banco=248, iguais=248, diferentes=0, só no banco=0, só na fonte=0
CAGED12_DESLIG: resposta=247 registros, sha256=69fb1006dd680e8f…, no escopo=247, banco=247, iguais=247, diferentes=0, só no banco=0, só na fonte=0
CAGED12_SALDO12: resposta=248 registros, sha256=349128db30fe1cb1…, no escopo=248, banco=248, iguais=248, diferentes=0, só no banco=0, só na fonte=0
CAGED12_ADMISN12: resposta=80 registros, sha256=a143677ecaa732e1…, no escopo=80, banco=80, iguais=80, diferentes=0, só no banco=0, só na fonte=0
CAGED12_DESLIGN12: resposta=80 registros, sha256=2d18b42436372f5f…, no escopo=80, banco=80, iguais=80, diferentes=0, só no banco=0, só na fonte=0
CAGED12_SALDON12: resposta=80 registros, sha256=939d39523544b833…, no escopo=80, banco=80, iguais=80, diferentes=0, só no banco=0, só na fonte=0
CAGED12_ADMISNAJU12: resposta=80 registros, sha256=aa990528f1dcf66f…, no escopo=80, banco=80, iguais=80, diferentes=0, só no banco=0, só na fonte=0
CAGED12_DESLIGNAJU12: resposta=80 registros, sha256=2219af1e2c178d9c…, no escopo=80, banco=80, iguais=80, diferentes=0, só no banco=0, só na fonte=0
CAGED12_SALDONAJU12: resposta=80 registros, sha256=e3c04c89641d9a90…, no escopo=80, banco=80, iguais=80, diferentes=0, só no banco=0, só na fonte=0
CONCLUÍDAS 11/11; NÃO CONCLUÍDAS: nenhuma
TOTAL iguais=36241 diferentes=0 só_no_banco=0 só_na_fonte=0
```

Nas séries `ADMISNC` e `DESLIGNC` o SHA-256 do corpo difere do arquivo guardado. Prova de que é só a **ordem** dos registros (resumo independente da ordem, sobre os 448.562 registros):

```text
ADMISNC: guardado: 448562 registros, resumo a6a2b9989a4e3df4, 1º registro ('Municípios', '4308433', '2020-01-01')
ADMISNC: agora:    448562 registros, resumo a6a2b9989a4e3df4, 1º registro ('Municípios', '4204756', '2020-01-01')
ADMISNC: MESMO CONJUNTO DE REGISTROS: True | MESMA ORDEM: False
DESLIGNC: guardado: 448562 registros, resumo f45aeb7db43b53e2, 1º registro ('Municípios', '2503407', '2020-01-01')
DESLIGNC: agora:    448562 registros, resumo f45aeb7db43b53e2, 1º registro ('Municípios', '3531100', '2020-01-01')
DESLIGNC: MESMO CONJUNTO DE REGISTROS: True | MESMA ORDEM: False
```

## 13. Incidentes de procedência encontrados (e corrigidos)

| Incidente | O que aconteceu | Situação |
|---|---|---|
| API de localidades do **IBGE** no pipeline (etapas 1 a 2) | A coleta consultava o IBGE a cada execução para obter a lista de municípios; os 217 municípios do banco referenciavam essa fonte. | Corrigido: consulta removida; cadastro passou a vir do `Territorios` do IpeaData; 217 de 217 códigos e nomes conferem; respostas antigas em `data/quarentena/` (não apagadas); fonte registrada como `legado_nao_autorizado`. |
| Exploração do **FTP do MTE** (etapa 1.5) | Para avaliar histórico anterior a 2020, listaram-se diretórios do FTP e **um** arquivo mensal foi baixado para inspecionar o layout. | Nada entrou no banco nem nos arquivos do projeto; o arquivo foi apagado e os números da exploração foram removidos da documentação. Não deveria ter havido download. |
| Conferência pontual de códigos com a API do IBGE (etapa 1) | Fora do pipeline. | Sem efeito nos dados. |

Verificação do que **não** vem do IpeaData: o banco não contém nenhum registro cuja origem seja o IBGE ou o MTE — todos os 36.241 apontam para um arquivo bruto de `data/raw/ipeadata/` com URL de `www.ipeadata.gov.br` (`CHECK` no banco).

## 14. Pendências e limitações

- **Validade no tempo:** a validação vale para a resposta do IpeaData no momento da auditoria. Se o IpeaData revisar valores, os registros divergentes saem das consultas até nova coleta incremental, importação e auditoria (`python main.py --modo incremental --importar`).
- **A auditoria exige o IpeaData no ar.** Com a fonte indisponível, ela termina `incompleta` e não altera nenhum status.
- **Hash do corpo:** em `ADMISNC`/`DESLIGNC` a API não garante a ordem dos registros; por isso a validação compara registro a registro.
- **Sem dados municipais antes de 2020-01** e **sem taxas percentuais** (o IpeaData não publica estoque de empregos por município). Nenhuma outra base foi usada para suprir isso.
- **11 municípios sem registro em 2024-01**: lacuna da publicação, não preenchida.
- **Constante sigla → código da UF** (`MA` → `21`) é configuração do projeto; conferida contra o IpeaData: código `21` = "Maranhão" (nível Estados).
- **Desempenho:** as views de dados validados acrescentam junções; as consultas passaram de ~8 ms para ~25–30 ms (ainda adequado). Rode `ANALYZE` após cargas grandes.
- **Coluna `presente_ipeadata`** em `municipios` ficou sempre verdadeira (o cadastro inteiro vem do IpeaData); mantida por compatibilidade.
- **Docker Compose** continua não executado nesta máquina (sem WSL2); o PostgreSQL roda com binários portáteis.
- Os testes de integração com o IpeaData **falham** (não passam em silêncio) se a fonte estiver indisponível.

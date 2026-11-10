# Modelo dos arquivos processados (origem da carga no PostgreSQL)

Gerado a partir de `coleta/esquema.py` por `python -m scripts.gerar_relatorio`. Descreve os arquivos de `data/processed`, que são a entrada do importador. O banco implementado na etapa 2 está em [modelagem_banco.md](modelagem_banco.md).

## Entidades recomendadas

| Entidade | Arquivo de origem | Chave natural | Conteúdo |
|---|---|---|---|
| municipio | `data/processed/consolidado/municipios.csv` | `cod_ibge` | Cadastro de municípios do IpeaData (entidade Territorios) |
| fonte_dados | `data/processed/consolidado/fontes.csv` | `fonte` | IpeaData (acesso) e MTE/Caged (origem estatística, não acessada) |
| serie | `data/processed/consolidado/series.csv` | `serie_codigo` | Metadados, metodologia, disponibilidade e última carga de cada série |
| observacao | `data/processed/<indicador>/ipeadata/<SERIE>/ano=AAAA.csv` | `fonte`, `serie_codigo`, `nivel_territorial`, `cod_territorio_original`, `data_referencia` | Fato: uma linha por série × território × mês (municípios do MA) |
| observacao (agregados) | `data/processed/agregados/ipeadata/<SERIE>.csv` e `data/processed/referencia_nacional/ipeadata/<SERIE>.csv` | `fonte`, `serie_codigo`, `nivel_territorial`, `cod_territorio_original`, `data_referencia` | Mesma estrutura; nível estado/brasil. Nunca misturado com o nível municipal |
| execucao_coleta | `data/processed/consolidado/execucoes.csv` e `data/checkpoints/execucoes.jsonl` | `execucao_id` | Rastreabilidade: quando, em que modo e com que resultado |

Relacionamentos: `observacao.serie_codigo` → `serie`; `observacao.cod_ibge` → `municipio` (quando `nivel_territorial = 'municipio'`); `observacao.execucao_id` → `execucao_coleta`; `serie.fonte` → `fonte_dados`.

## Observação (tabela de fatos)

Chave natural: (`fonte`, `serie_codigo`, `nivel_territorial`, `cod_territorio_original`, `data_referencia`). `serie_codigo` já identifica indicador e metodologia; nível e código territorial evitam colisão entre município, UF e Brasil no mesmo mês. Recomenda-se `UNIQUE` sobre essas colunas.

| Coluna | Tipo (pandas) | Tipo PostgreSQL sugerido | Anulável | Descrição |
|---|---|---|---|---|
| `fonte` | string | text | não | Fonte de acesso (IpeaData) |
| `fonte_original` | string | text | não | Fonte primária informada nos metadados (FNTSIGLA) |
| `serie_codigo` | string | text | não | Código da série no IpeaData (SERCODIGO) |
| `serie_nome` | string | text | não | Nome da série (SERNOME) |
| `indicador` | string | text | não | admissoes \| desligamentos \| saldo |
| `metodologia` | string | text | não | CAGED tradicional \| Novo Caged - sem ajuste \| Novo Caged - com ajuste |
| `periodicidade` | string | text | não | Periodicidade (PERNOME), ex.: Mensal |
| `unidade` | string | text | não | Unidade (UNINOME), ex.: Pessoa |
| `nivel_territorial` | string | text | não | municipio \| estado \| brasil |
| `nivel_territorial_original` | string | text | sim | NIVNOME como veio da API (vazio em séries nacionais) |
| `cod_territorio_original` | string | text | sim | TERCODIGO como veio da API (vazio em séries nacionais) |
| `cod_ibge` | string | varchar(7) | sim | Código IBGE: 7 dígitos (município) ou 2 (UF); vazio para Brasil |
| `territorio_nome` | string | text | não | Nome do município publicado no IpeaData, sigla da UF ou 'Brasil' |
| `uf` | string | char(2) | sim | Sigla da UF; vazio para Brasil |
| `data_referencia` | datetime64[ns] | date | não | Primeiro dia do período de referência |
| `ano` | Int64 | smallint | não | Ano de referência |
| `mes` | Int64 | smallint | sim | Mês de referência (séries mensais) |
| `valor` | Int64 | integer | não | Valor publicado; nunca preenchido quando ausente |
| `serie_atualizada_em` | string | timestamptz | sim | SERATUALIZACAO dos metadados no momento da coleta |
| `coletado_em_utc` | string | timestamptz | não | Momento do download da resposta bruta |
| `execucao_id` | string | text | não | Execução de coleta que gravou o valor |
| `arquivo_bruto` | string | text | não | Resposta original preservada em data/raw |

## Município

| Coluna | Tipo (pandas) | Tipo PostgreSQL sugerido | Anulável | Descrição |
|---|---|---|---|---|
| `cod_ibge` | string | char(7) | não | Código municipal de 7 dígitos (IpeaData, Territorios) |
| `municipio` | string | text | não | Nome publicado no IpeaData |
| `uf` | string | char(2) | não | Sigla da UF |
| `cod_uf` | string | char(2) | não | Código da UF (2 primeiros dígitos do código municipal) |
| `nome_ipeadata` | string | text | sim | Nome no cadastro de territórios do IpeaData |
| `capital` | boolean | boolean | sim | Capital da UF (IpeaData) |
| `area_km2` | Float64 | numeric(12,2) | sim | Área em km² (IpeaData) |
| `presente_ipeadata` | boolean | boolean | não | Consta no cadastro de territórios do IpeaData |

## Painel município × mês (visão derivada)

`data/processed/consolidado/painel_municipal_mensal.csv` é derivado das observações (grade completa com situação de cada mês e saldo). Na etapa 2 pode ser uma *view* em vez de uma tabela.

| Coluna | Tipo (pandas) | Tipo PostgreSQL sugerido | Anulável | Descrição |
|---|---|---|---|---|
| `cod_ibge` | string | char(7) | não | Código municipal de 7 dígitos (publicado no IpeaData) |
| `municipio` | string | text | não | Nome publicado no IpeaData |
| `uf` | string | char(2) | não | Sigla da UF |
| `data_referencia` | datetime64[ns] | date | não | Mês de referência |
| `ano` | Int64 | smallint | não | Ano |
| `mes` | Int64 | smallint | não | Mês |
| `admissoes` | Int64 | integer | sim | Admissões (vazio se não publicado) |
| `desligamentos` | Int64 | integer | sim | Desligamentos (vazio se não publicado) |
| `saldo` | Int64 | integer | sim | admissoes - desligamentos, só quando ambos existem |
| `status_admissoes` | string | text | não | Situação da observação (ver STATUS_OBSERVACAO) |
| `status_desligamentos` | string | text | não | Situação da observação (ver STATUS_OBSERVACAO) |
| `serie_admissoes` | string | text | não | Série de origem das admissões |
| `serie_desligamentos` | string | text | não | Série de origem dos desligamentos |
| `metodologia` | string | text | não | Metodologia comum às duas séries |
| `fonte` | string | text | não | Fonte de acesso |

Situações possíveis (`status_*`):

| Situação | Significado |
|---|---|
| `valor_encontrado` | Observação publicada com valor maior que zero |
| `zero_encontrado` | Observação publicada com valor zero |
| `observacao_ausente` | Período coberto pela série, mas sem registro para o território |
| `nao_disponibilizado_pela_fonte` | Período fora da disponibilidade da série |
| `falha_coleta` | A coleta falhou e não há dados válidos para verificar |

## Regras para a carga

- **Formato:** CSV UTF-8, separador vírgula, cabeçalho, datas `AAAA-MM-DD`, sem índice. Compatível com `COPY ... WITH (FORMAT csv, HEADER true)`.
- **Texto vazio** significa "não se aplica" (ex.: `cod_ibge` do Brasil); **número vazio** significa "não publicado". Nunca carregar vazio como zero.
- **Lotes:** uma partição por série e ano (~2,6 mil linhas por série/ano no nível municipal).
- **Deduplicação:** `INSERT ... ON CONFLICT (chave natural) DO UPDATE` somente quando `valor` mudou; os arquivos já não têm chaves repetidas (validado por `scripts.validar_dados`).
- **Atualização:** recarregar apenas as partições listadas no `manifesto.json` com `execucao_id` posterior à última carga no banco.
- **Integridade:** conferir o SHA-256 de cada arquivo contra `data/processed/manifesto.json` antes da carga.
- **Proveniência:** manter `arquivo_bruto`, `coletado_em_utc`, `serie_atualizada_em` e `execucao_id` na tabela de fatos.
- **Metodologias:** nunca somar ou emendar observações de `metodologia` diferente.

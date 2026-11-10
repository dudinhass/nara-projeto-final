# Arquitetura

## Visão geral

Monorepo com um componente por diretório. A coleta é um pacote Python
instalável (`coleta/`); os scripts em `scripts/` só interpretam argumentos e
imprimem resultados.

```text
 IpeaData (OData v4) — ÚNICA fonte de dados do projeto
                      ▼
 ┌──────────────────────────── coleta/pipeline.py ─────────────────────────────┐
 │ territorios ─► [por série] metadados ─► download em fluxo ─► validação JSON  │
 │                 ─► processamento em lotes ─► comparação com a base           │
 │                 ─► gravação atômica ─► releitura ─► checkpoint "concluída"   │
 │             ─► consolidação (painel, cadastros, matrizes de cobertura)       │
 └──────────────────────────────────────────────────────────────────────────────┘
        │ data/raw (bruto + .meta.json)   data/processed (partições CSV + manifesto)
        │ data/checkpoints (estado + execuções)   data/reports (cobertura, validação)
        ▼  (etapa 2)
   database/ — PostgreSQL ──► backend/ — FastAPI ──► frontend/ — Next.js
```

## Módulos

| Módulo | Responsabilidade |
|---|---|
| `config.py` | Toda a configuração: API, modo, lote, concorrência, janela incremental, UF, política territorial, diretórios e catálogo de séries |
| `ipea_client.py` | `requests.Session`, timeouts, novas tentativas com backoff exponencial, HTTP 429 com `Retry-After`, 5xx, limite de taxa entre threads, download em fluxo com verificação de `Content-Length` e SHA-256 |
| `leitor_odata.py` | Validação e leitura em fluxo (ijson) dos JSONs gravados, em lotes; detecta `@odata.nextLink` |
| `territorios.py` | Cadastro de municípios do IpeaData (`Territorios`): validação estrutural e política estrita/alerta |
| `procedencia.py` | Verificações puras: host autorizado, URL = série esperada, metadados da série, comparação de metadados |
| `transformacao.py` | Classifica cada registro (aceito / excluído / rejeitado com motivo), converte datas e valores, deduplica, monta o painel |
| `incremental.py` | Compara base × snapshot: novas, revisadas na/fora da janela, ausentes na fonte; aplica com controle |
| `cobertura.py` | Matrizes município × mês e município × ano × indicador com as situações exigidas |
| `checkpoint.py` | Estado por tarefa, retomada, histórico de execuções (JSONL) |
| `repositorio.py` | Caminhos das partições, leitura/gravação das séries e manifesto de integridade |
| `armazenamento.py` | Escrita atômica, hashes, partições por ano, limpeza de sobras |
| `esquema.py` | Colunas, tipos, chaves naturais e tipos PostgreSQL sugeridos (fonte única) |
| `pipeline.py` | Orquestração dos modos FULL e INCREMENTAL |
| `validacao.py` | Verificações sobre a base persistida (críticas × metodológicas) |
| `relatorios.py` | Gera `docs/cobertura_historica.md`, `docs/relatorio_validacao_etapa1.md`, `docs/modelo_dados.md` |
| `investigacao.py` | Varredura do catálogo e perfil de cada série |
| `logs.py` | Console + `logs/coleta.log` (texto) + `logs/coleta.jsonl` (JSON estruturado) |

## Decisões técnicas

### Pacote plano `coleta/` em vez de `src/` com subpacotes

A estrutura sugerida (`src/config`, `src/clients`, `src/extractors`, …) criaria sete subpacotes com um
módulo cada, mais indireção sem ganho. Os 16 módulos têm nomes que já dizem a camada. O pacote foi
mantido (preservando a etapa anterior) e instalado com `pip install -e .`, o que faz os imports
funcionarem a partir da raiz sem mexer em `sys.path`.

### Download inteiro + recorte local

A API ignora `$filter`/`$top` no endpoint de valores (verificado), então não existe extração por
município ou por período no servidor: cada série é baixada inteira (~64 MB para as municipais) e o
Maranhão é recortado no cliente. Milhares de requisições por município não são possíveis nem
necessárias. Consequências:

- **Memória:** o corpo vai direto para disco (gzip) em blocos de 1 MB; a leitura usa `ijson` em lotes
  (`COLETA_TAMANHO_LOTE`). Só as observações do MA (~17 mil por série) ficam em memória.
- **Integridade:** o tamanho recebido é comparado ao `Content-Length`; download truncado é retentado.
- **Checkpoint por série:** a unidade de trabalho é a série. Dentro dela há duas etapas persistidas:
  `baixada` (brutos validados, com SHA-256 registrado e reaproveitáveis na retomada) e `persistida`.

### Modos FULL e INCREMENTAL

- **FULL** substitui a base de cada série pelo snapshot atual. Antes, compara com a base anterior e
  registra as diferenças em `data/reports/alteracoes/`, para não sobrescrever sem controle.
- **INCREMENTAL** consulta `SERATUALIZACAO`. Se não mudou, não baixa nada. Se mudou, baixa o snapshot
  e aplica observações novas e revisões dentro da janela (`INCREMENTAL_JANELA_MESES`). Revisões
  antigas e observações que sumiram da fonte são só registradas. Só as partições afetadas são
  regravadas. Rodar de novo sem mudança na fonte não altera nada (idempotente).

### Checkpoint e retomada

- Cada tarefa só vira `concluida` depois de gravar, reler e conferir chaves e valores.
- Execução com falha ou interrompida continua "em andamento"; o próximo comando do mesmo modo
  retoma só o que falta. `--reiniciar` descarta a execução (fica registrada como `descartada`).
- Na inicialização, sobras `.tmp`/`.part` e brutos sem `.meta.json` são removidos e listados.

### Concorrência

`COLETA_MAX_CONCORRENCIA` (padrão 1) controla downloads simultâneos, com um cliente por thread e
limite de taxa compartilhado. O padrão sequencial é deliberado: são ~13 requisições, duas delas
grandes, num servidor público.

### Territórios

O cadastro vem da entidade `Territorios` do IpeaData (nenhuma lista externa), guardado em
`data/raw/ipeadata/territorios/`. A validação é estrutural: códigos de 7 dígitos da UF, sem repetição, nomes
preenchidos e o total esperado (217 no MA). Registros de outras UFs, regiões e áreas metropolitanas são
**excluídos** (contados, não rejeitados). Códigos do MA fora do cadastro são **rejeitados**. Na política
`estrita`, qualquer problema interrompe a coleta.

### Procedência: só o IpeaData

Regra do projeto: todos os dados vêm do IpeaData. Como é garantida, em camadas:

1. **Cliente HTTP** (`ipea_client.py`): só aceita `https` e o host `www.ipeadata.gov.br`, na URL base, nos links de
   paginação e no endereço final de cada resposta; redirecionamentos não são seguidos.
2. **Pipeline**: lista fechada de séries; cada série precisa passar nos metadados do IpeaData (código, base, periodicidade,
   unidade) antes de ser baixada; cada observação precisa trazer o `SERCODIGO` da série; séries nacionais só aceitam o nível
   Brasil.
3. **Importador**: recusa série ou arquivo de origem fora da configuração, fonte diferente de IpeaData e bruto fora de
   `data/raw/ipeadata/`. Observações novas ou revisadas entram como `nao_validado`.
4. **Auditoria** (`banco/auditoria.py`): baixa de novo cada série e compara cada observação com o arquivo bruto preservado
   (SHA-256) e com a resposta oficial atual. Só então marca `validado_ipeadata`.
5. **Banco**: `CHECK`s e gatilhos impedem validação sem snapshot, fonte não autorizada e snapshot de outra série; as views
   `vw_*_validados` são a única porta das consultas analíticas.

Uma checagem estática nos testes varre o código atrás de qualquer endereço que não seja do IpeaData.

### Metodologias

Cada observação carrega `serie_codigo` e `metodologia`. CAGED tradicional e Novo Caged ficam em
séries distintas, e o painel só calcula saldo entre séries de mesma metodologia (verificado em
código). Séries nacionais vão para `referencia_nacional/` e nunca são convertidas em dado municipal.

## Camada de banco (etapa 2)

| Módulo | Responsabilidade |
|---|---|
| `banco/modelos.py` | Modelos SQLAlchemy 2.x (espelham a migração Alembic) |
| `banco/conexao.py` | Engine (`pool_pre_ping`, timeout), fábrica de sessões, transação, verificação com novas tentativas |
| `banco/repositorios.py` | Upsert de fontes, municípios e séries; controle de arquivos importados |
| `banco/importacao.py` | Importação FULL/INCREMENTAL: lotes, `COPY`, upsert, revisões, inconsistências, trava |
| `banco/consultas.py` | Consultas analíticas (SQL em `database/queries/`) com as regras metodológicas |
| `banco/reconciliacao.py` | Arquivos processados × banco (contagem, soma, MD5 por série/ano) |
| `banco/verificacao.py` | Migração, objetos, integridade, `EXPLAIN ANALYZE` |
| `banco/relatorio.py` | Gera `docs/relatorio_etapa2.md` |

Decisões:

- **`banco/` como pacote único de persistência**, em vez de modelos em `backend/app/models`:
  o importador (sem FastAPI) e a futura API precisam dos mesmos modelos e consultas. Isso evita
  configurações duplicadas entre `src`, `backend` e `database`.
- **Configuração no mesmo módulo central** (`coleta/config.py` → `ConfigBanco`); a senha só
  vem do `.env`.
- **Migrações escritas pelo Alembic e revisadas**; `create_all()` não é usado nem nos testes
  (a fixture aplica `downgrade base` + `upgrade head` no banco de testes).
- **A entrada do importador são os arquivos processados + `manifesto.json`** da etapa 1, e não
  a API: o banco é carregado a partir de dados já validados e rastreáveis, e o SHA-256 de cada
  arquivo é conferido antes da carga.
- **Ambiente sem Docker**: nesta máquina o Docker Desktop não inicia (falta a Plataforma de
  Máquina Virtual/WSL2, que exige administrador). O PostgreSQL 17 roda com os binários
  portáteis oficiais (`scripts/postgres_local.py`), com dados fora do OneDrive. O
  `compose.yaml` usa a mesma versão (`postgres:17`) para quem tiver Docker.

### Preparação para as próximas etapas

`backend/` (FastAPI) e `frontend/` (Next.js) continuam reservados. A API deve importar
`banco.conexao` e `banco.consultas`.

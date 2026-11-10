# Roadmap

| Etapa | Escopo | Tecnologias | Situação |
|---|---|---|---|
| 1 | Investigação e coleta de dados | Python, requests, pandas, ijson, IpeaData | **Concluída** |
| 1.5 | Auditoria, coleta histórica completa, checkpoint, modos FULL/INCREMENTAL, cobertura | Python | **Concluída** |
| 2 | Modelagem e armazenamento | PostgreSQL 17, SQLAlchemy 2, Alembic, psycopg 3 | **Concluída** |
| 2.5 | Auditoria de procedência: uso exclusivo do IpeaData | Python, PostgreSQL | **Concluída** |
| 3 | Desenvolvimento da API | Python, FastAPI | **Concluída** |
| 4 | Desenvolvimento da interface | Next.js, CSS | Pendente |
| 5 | Integração, testes e apresentação | Todos os componentes | Pendente |

## Etapa 1 — Investigação e coleta

Investigação da API, séries candidatas e diagnóstico em [investigacao_ipeadata.md](investigacao_ipeadata.md).

## Etapa 1.5 — Coleta histórica completa

Entregue:

- Base histórica completa do IpeaData: os 217 municípios do MA, jan/2020–ago/2026 (toda a
  disponibilidade municipal), além de UF, Brasil e 9 séries nacionais de referência (desde 1999-05).
- Pipeline com modos FULL e INCREMENTAL, checkpoint, retomada, escrita atômica e download em fluxo.
- Validação territorial estrutural sobre o cadastro do próprio IpeaData (política estrita/alerta).
- Matrizes de cobertura município × mês e município × ano × indicador.
- Relatórios gerados a partir dos dados: [cobertura_historica.md](cobertura_historica.md),
  [relatorio_validacao_etapa1.md](relatorio_validacao_etapa1.md), [modelo_dados.md](modelo_dados.md).
- Testes unitários e de integração.

Decisão registrada: **só IpeaData**. Microdados do MTE (CAGED 2007–2019) não são utilizados; o IBGE foi removido do pipeline (ver auditoria).

## Etapa 2 — Modelagem e armazenamento (PostgreSQL)

Entregue (detalhes em [modelagem_banco.md](modelagem_banco.md) e [relatorio_etapa2.md](relatorio_etapa2.md)):

- Esquema normalizado com 8 tabelas e uma view, criado pela migração Alembic `0001`.
- Importador FULL/INCREMENTAL idempotente (lotes, `COPY`, upsert, revisões, inconsistências, trava).
- Carga histórica completa no banco principal, reconciliada com os arquivos processados.
- Consultas analíticas (`banco/consultas.py`, `database/queries/`) e CLI `scripts.consultar`.
- Testes de integração em banco PostgreSQL de testes isolado.

## Etapa 2.5 — Auditoria de procedência

Entregue (detalhes em [auditoria_origem_ipeadata.md](auditoria_origem_ipeadata.md)):

- Remoção do IBGE do pipeline; cadastro de municípios vindo do IpeaData.
- Cliente HTTP restrito ao host do IpeaData; verificação de metadados e de código de série em cada observação.
- Migração `0002`: status de procedência, snapshots de origem, gatilhos e views de dados validados.
- Auditoria que compara cada observação do banco com a resposta oficial atual e com o arquivo bruto preservado.

## Etapa 3 — API (FastAPI)

- Endpoints: municípios, série mensal por município, ranking por período, totais estaduais,
  cobertura (situação de cada mês). **Só leem as views `vw_*_validados`.**
- A API lê só do PostgreSQL usando `banco.consultas`; o pacote `coleta` + `banco.importacao` continuam responsáveis pelas cargas.
- Paginação por chave (*keyset*) nos endpoints de listagem.

## Etapa 4 — Interface (Next.js)

- Painéis: evolução mensal/anual, comparação entre municípios, ranking, saldo.
- Exibir sempre fonte, metodologia e data de atualização; mostrar lacunas como lacunas (não como zero);
  não exibir taxas sem denominador válido.

## Etapa 5 — Integração, testes e apresentação

- Testes ponta a ponta (coleta → banco → API → interface).
- Agendamento da atualização incremental (ex.: mensal, após a divulgação do Novo Caged).
- Documentação final e apresentação.

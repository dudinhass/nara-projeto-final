# Dashboard de Admissões e Demissões dos Municípios do Maranhão

Aplicação para analisar admissões, desligamentos e o saldo do emprego formal nos
**217 municípios do Maranhão**, com dados do **Novo Caged** obtidos pelo **IpeaData**.

> **Situação:** etapas 1 (coleta) e 2 (PostgreSQL) concluídas. A base histórica completa
> disponível está coletada, validada, carregada no PostgreSQL e reconciliada. API (FastAPI)
> e interface (Next.js) ainda não foram implementadas (veja o [roadmap](docs/roadmap.md)).

## Arquitetura

```text
IpeaData ─► coleta/ ─► data/processed ─► banco/ (importador) ─► PostgreSQL ─► backend/ (FastAPI) ─► frontend/ (Next.js)
            etapa 1     arquivos + manifesto     etapa 2          etapa 2        etapa 3              etapa 4
```

| Pacote | Papel |
|---|---|
| `coleta/` | Coleta do IpeaData (FULL/INCREMENTAL, checkpoint), validação, arquivos processados |
| `banco/` | Modelos SQLAlchemy, conexão, importação para o PostgreSQL, consultas analíticas, reconciliação |
| `database/` | Migrações Alembic, consultas SQL, script de inicialização do Docker |
| `scripts/` | Linha de comando de todas as etapas |

Detalhes: [arquitetura](docs/arquitetura.md) · [modelagem do banco](docs/modelagem_banco.md).

## Requisitos

- Python 3.11+
- PostgreSQL 17, por **uma** destas vias:
  - **Docker Compose** (`compose.yaml`), ou
  - **binários portáteis oficiais**, sem Docker nem permissão de administrador
    (`scripts/postgres_local.py`).

## Instalação

```powershell
cd emprego-maranhao
python -m venv .venv
.\.venv\Scripts\Activate.ps1           # se bloquear: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env            # e troque POSTGRES_PASSWORD por uma senha sua
```

O `.env` não é versionado. Todas as opções estão em [.env.example](.env.example).

## PostgreSQL

### Opção A — Docker Compose

```powershell
docker compose up -d          # sobe o PostgreSQL 17 (cria também o banco de testes)
docker compose ps             # aguarde "healthy"
docker compose logs postgres
docker compose down           # para; os dados ficam no volume (não use "down -v")
```

### Opção B — sem Docker (binários portáteis)

Use esta opção quando o Docker não roda (por exemplo, Windows sem WSL2). Os binários e os
dados ficam em `%LOCALAPPDATA%\emprego-maranhao`, fora do OneDrive.

```powershell
# 1ª vez: baixe e extraia os binários oficiais (EnterpriseDB) para %LOCALAPPDATA%\emprego-maranhao\pg17
#   https://get.enterprisedb.com/postgresql/postgresql-17.11-1-windows-x64-binaries.zip
python -m scripts.postgres_local iniciar   # cria o cluster (1ª vez), sobe o servidor e cria os bancos
python -m scripts.postgres_local status
python -m scripts.postgres_local parar
```

### Migrações

```powershell
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini current
alembic -c database/alembic.ini check      # confere se modelos e banco estão iguais
```

## Fluxo de dados

```powershell
# 1. Coleta (etapa 1)
python -m scripts.coletar_historico         # FULL: histórico completo
python -m scripts.atualizar_dados           # INCREMENTAL: novidades da fonte
python -m scripts.validar_dados

# 2. Banco (etapa 2)
python -m scripts.importar_postgresql --tipo full          # carga histórica completa
python -m scripts.importar_postgresql --tipo incremental   # só arquivos novos ou alterados
python -m scripts.auditar_procedencia     # comprova a procedência contra o IpeaData (obrigatório antes de consultar)
python -m scripts.reconciliar_dados        # arquivos processados × banco
python -m scripts.verificar_banco          # migração, integridade, EXPLAIN ANALYZE

# 3. Relatórios
python -m scripts.gerar_relatorio          # atualiza os relatórios em docs/
```

Tudo de uma vez (inclui a auditoria): `python main.py --modo incremental --importar`.

As importações são **idempotentes**: repetir não duplica nada. Uma importação interrompida é
retomada pela próxima `--tipo incremental`. Valores revisados pela fonte são atualizados, e o
valor anterior fica guardado em `revisoes_registros`.

## Procedência: somente dados do IpeaData

**Regra obrigatória:** todos os dados vêm do IpeaData. Obter dados direto do Ministério do Trabalho, do IBGE ou de
qualquer outro portal é proibido; o CAGED/Novo CAGED só vale quando publicado pelo IpeaData.

- O cliente HTTP só aceita `https://www.ipeadata.gov.br/` (inclusive em paginação) e não segue redirecionamentos.
- Cada série passa pela conferência de metadados do IpeaData; cada observação precisa trazer o código da série.
- O cadastro de municípios vem da entidade `Territorios` do IpeaData.
- No banco, cada observação tem `status_procedencia` e aponta para o arquivo bruto (URL, SHA-256, horário) que a originou.
  Observações novas ou revisadas entram como `nao_validado`.
- A **auditoria** baixa de novo cada série e compara com o banco; só o que confere vira `validado_ipeadata`.
- As consultas leem somente as views `vw_*_validados`.

```powershell
python -m scripts.importar_postgresql --tipo incremental    # leva as novidades ao banco (como "não validado")
python -m scripts.auditar_procedencia                       # compara com o IpeaData e valida (~1,5 min)
python -m scripts.gerar_relatorio                           # gera docs/auditoria_origem_ipeadata.md
```

Resultado e evidências: [docs/auditoria_origem_ipeadata.md](docs/auditoria_origem_ipeadata.md).

## Consultas

Pela linha de comando:

```powershell
python -m scripts.consultar ultima
python -m scripts.consultar ranking --indicador saldo --inicio 2025-01 --fim 2025-12 --limite 10
python -m scripts.consultar municipio 2111300
python -m scripts.consultar mensal 2111300 --inicio 2024-01 --fim 2024-12
python -m scripts.consultar uf --inicio 2025-01 --fim 2025-12
python -m scripts.consultar comparar 2111300 2105302 2103000 --inicio 2025-01 --fim 2025-12
python -m scripts.consultar periodos --a 2024-01:2024-12 --b 2025-01:2025-12
python -m scripts.consultar nacional --indicador admissoes
```

Pelo Python (base para a API):

```python
from banco.conexao import criar_engine
from banco.consultas import ConsultasEmprego

c = ConsultasEmprego(criar_engine())
c.ranking_municipios("saldo", "2025-01", "2025-12", limite=10)
c.historico_municipio("2111300")
```

Ou direto no SQL: `vw_movimentacao_mensal` e os arquivos de `database/queries/`.

**Regras das consultas:**
- uma metodologia por vez, e o saldo só é calculado quando admissões e desligamentos existem;
- meses sem observação aparecem como `NULL`, nunca como zero;
- não há taxas percentuais, porque falta um denominador oficial.

## Testes

```powershell
pytest                                      # unitários + PostgreSQL de testes (pulados se o servidor estiver parado)
$env:IPEA_TESTES_INTEGRACAO = "1"; pytest   # inclui as requisições reais ao IpeaData
pytest --junitxml=data/reports/pytest.xml   # registra o resultado para os relatórios
```

Os testes de banco usam **somente** `POSTGRES_TEST_DB`. A fixture se recusa a rodar se o nome
não terminar em `_test` ou coincidir com o banco principal. O esquema de testes é recriado
pelas migrações Alembic a cada sessão.

## Estrutura

```text
emprego-maranhao/
├── coleta/            # etapa 1: cliente IpeaData, pipeline, validação, relatórios
├── banco/             # etapa 2: modelos, conexão, importação, consultas, reconciliação, verificação
├── database/          # alembic.ini, migrations/, queries/*.sql, docker/init/
├── scripts/           # comandos (coleta, banco, consultas, relatórios, postgres_local)
├── tests/unit/        # sem rede e sem banco
├── tests/integration/ # PostgreSQL de testes e APIs reais
├── data/              # raw/, processed/, checkpoints/, reports/ (não versionado)
├── docs/              # arquitetura, investigação, cobertura, modelagem, relatórios das etapas, roadmap
├── backend/  frontend/          # reservados (etapas 3 e 4)
├── compose.yaml  .env.example  pyproject.toml  requirements.txt  main.py
```

## Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| `Não foi possível conectar a postgresql+psycopg://...` | Servidor parado: `python -m scripts.postgres_local status` ou `docker compose ps`. Confira `POSTGRES_*` no `.env`. |
| `docker: failed to connect to the docker API` | Docker Desktop não iniciado ou sem WSL2/Plataforma de Máquina Virtual (exige administrador). Use a opção B. |
| `password authentication failed` | A senha do `.env` difere da usada ao criar o cluster ou o volume. |
| `A coleta ... está em andamento` | Há uma coleta incompleta: conclua com `python -m scripts.coletar_historico` antes de importar. |
| `Outra importação está em andamento` | Já existe uma importação rodando neste banco (trava `pg_advisory_lock`). |
| `arquivo_alterado_apos_coleta` | Um CSV processado foi editado fora do pipeline; rode a coleta de novo para regenerar o arquivo e o manifesto. |
| Testes de banco "skipped" | PostgreSQL de testes inacessível; suba o servidor e confira `POSTGRES_TEST_DB`. |
| `PermissionError` ao gravar no OneDrive | O sincronizador bloqueia o arquivo por instantes; o código repete a gravação. Persistindo, pause a sincronização. |

## Limitações da fonte

- **Dados municipais só desde jan/2020** (Novo Caged no IpeaData). O CAGED tradicional existe
  só como total nacional (1999–2019) e não é emendado ao Novo Caged.
- **Séries municipais "sem ajuste"**: cerca de 3% abaixo da versão "com ajuste" no total nacional.
- **11 municípios sem registro em jan/2024**: é uma lacuna da publicação. As lacunas não são
  preenchidas.
- **Sem taxas percentuais**: falta o estoque de empregos por município.

Detalhes em [investigacao_ipeadata.md](docs/investigacao_ipeadata.md) e
[cobertura_historica.md](docs/cobertura_historica.md).

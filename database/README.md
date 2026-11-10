# database/

Infraestrutura do PostgreSQL (etapa 2). Modelagem: [docs/modelagem_banco.md](../docs/modelagem_banco.md).

| Caminho | Conteúdo |
|---|---|
| `alembic.ini` | Configuração do Alembic (a URL vem do `.env`, nunca deste arquivo) |
| `migrations/env.py` | Ambiente das migrações (usa `banco.modelos.Base.metadata`) |
| `migrations/versions/` | Histórico versionado de migrações |
| `queries/*.sql` | Consultas analíticas parametrizadas (usadas por `banco/consultas.py`; também executáveis no `psql`) |
| `docker/init/` | Script que cria o banco de testes na 1ª inicialização do container |

```powershell
alembic -c database/alembic.ini upgrade head      # aplica as migrações
alembic -c database/alembic.ini current           # revisão aplicada
alembic -c database/alembic.ini check             # confere modelos × banco
alembic -c database/alembic.ini revision --autogenerate -m "descricao"   # nova migração (revise o arquivo!)
```

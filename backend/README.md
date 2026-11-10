# Backend — API FastAPI

API somente leitura em Python + FastAPI para o dashboard de emprego do Maranhão.
Ela usa exclusivamente `banco.consultas`, mantendo centralizadas as regras de
procedência, metodologia e lacunas do PostgreSQL.

## Executar localmente

Na raiz de `emprego-maranhao`, com o `.venv` ativo e o PostgreSQL configurado no `.env`:

```powershell
$env:PYTHONPATH = "backend"
uvicorn app.main:app --app-dir backend --reload
```

Documentação interativa: `http://localhost:8000/docs`.

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health/live
Invoke-RestMethod http://localhost:8000/api/v1/health/ready
```

`live` não depende do banco. `ready` confirma a conexão com o PostgreSQL e retorna
HTTP 503 quando o banco está indisponível.

## Endpoints

| Endpoint | Uso |
|---|---|
| `GET /api/v1/health/live` | processo ativo |
| `GET /api/v1/health/ready` | processo + PostgreSQL disponível |
| `GET /api/v1/meta` | fonte, metodologia e regras para o front |
| `GET /api/v1/municipios` | municípios validados, com paginação por cursor |
| `GET /api/v1/municipios/{cod_ibge}/historico` | cadastro, série mensal e anual |
| `GET /api/v1/municipios/{cod_ibge}/mensal` | evolução mensal com lacunas explícitas |
| `GET /api/v1/municipios/{cod_ibge}/anual` | evolução anual e indicação de ano completo |
| `GET /api/v1/ranking` | ranking por admissões, desligamentos ou saldo |
| `GET /api/v1/totais/uf` | total oficial da UF versus soma municipal |
| `GET /api/v1/indicadores` | resumo do período |
| `GET /api/v1/cobertura` | cobertura das séries e competências |
| `GET /api/v1/comparar-periodos` | comparação absoluta entre dois períodos |

Todos os endpoints de dados leem views `vw_*_validados`. Não há endpoint de escrita;
coleta, importação e auditoria continuam nos scripts existentes.

## Testes

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -q
```

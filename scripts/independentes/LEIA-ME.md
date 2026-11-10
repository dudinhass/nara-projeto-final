# Verificações independentes

Scripts **sem nenhum import do projeto** (só `requests`, `ijson`, `psycopg`), para conferir os dados por um caminho
de código diferente do pipeline e da auditoria.

| Script | O que prova |
|---|---|
| `verificar_valores.py` | Baixa cada série direto do IpeaData e compara cada valor com o banco (SQL puro) |
| `provar_ordem_registros.py` | Mostra que o arquivo bruto guardado e a resposta atual têm o **mesmo conjunto de registros** (resumo independente da ordem), mesmo quando o SHA-256 do corpo difere |

```powershell
python scripts\independentes\verificar_valores.py ADMISNC DESLIGNC CAGED12_ADMIS
python scripts\independentes\provar_ordem_registros.py ADMISNC data\raw\ipeadata\ADMISNC\<arquivo>.json.gz
```

As saídas das execuções de 26/10/2026 estão em `data/reports/evidencias_manuais/`.

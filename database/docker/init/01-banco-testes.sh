#!/bin/sh
# Executado pelo container postgres só na primeira inicialização do volume.
# Cria o banco de testes isolado (os testes de integração nunca usam o banco principal).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
SELECT 'CREATE DATABASE "${POSTGRES_TEST_DB}" OWNER "${POSTGRES_USER}"'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_TEST_DB}')\gexec
SQL

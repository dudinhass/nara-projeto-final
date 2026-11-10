from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.main import app
from app.api import routes


client = TestClient(app)


def test_live_e_documentacao_openapi():
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "/api/v1/ranking" in openapi.json()["paths"]


def test_meta_expoe_regras_do_projeto():
    body = client.get("/api/v1/meta").json()
    assert body["fonte"] == "IpeaData"
    assert "procedência validada" in body["regra_procedencia"]
    assert "nulos" in body["regra_lacunas"]


def test_municipios_usa_paginacao_keyset(monkeypatch):
    monkeypatch.setattr(
        routes,
        "listar_municipios",
        lambda cursor, limite: ([{"cod_ibge": "2100055", "nome": "Açailândia"}], "2100055"),
    )
    response = client.get("/api/v1/municipios?limite=1")
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"cod_ibge": "2100055", "nome": "Açailândia"}],
        "next_cursor": "2100055",
        "has_more": True,
    }


def test_ranking_delega_para_camada_de_consultas(monkeypatch):
    class FakeConsultas:
        def ranking_municipios(self, indicador, inicio, fim, limite, ordem, metodologia):
            return [{"posicao": 1, "municipio": "São Luís", "saldo": 10}]

    monkeypatch.setattr(routes, "get_consultas", lambda: FakeConsultas())
    response = client.get("/api/v1/ranking?inicio=2025-01&fim=2025-12")
    assert response.status_code == 200
    assert response.json()[0]["saldo"] == 10

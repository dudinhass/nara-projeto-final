from __future__ import annotations

import os
from dataclasses import dataclass

from coleta.config import carregar_config_banco, carregar_config_coleta


def _origins() -> list[str]:
    value = os.getenv("API_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001")
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    api_version: str = os.getenv("API_VERSION", "1.0.0")
    uf: str = os.getenv("UF_INTERESSE", "MA").upper()
    cod_uf: str = "21"
    cors_origins: list[str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cors_origins", _origins())

    @property
    def database_url(self) -> str:
        return carregar_config_banco().url_principal

    @property
    def metodologia_padrao(self) -> str:
        return "Novo Caged - sem ajuste"


settings = Settings()

# Fail early if a deployment tries to serve another UF without updating its code.
if settings.uf not in {"MA"}:
    raise RuntimeError(f"UF_INTERESSE não suportada pela API: {settings.uf}")

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title="Dashboard de Emprego do Maranhão",
    description=(
        "API somente leitura para admissões, desligamentos e saldo do emprego formal. "
        "Os dados exibidos são exclusivamente os validados pelo IpeaData."
    ),
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_prefix)

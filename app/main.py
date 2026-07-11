"""FastAPI application factory (brief Section 4.1).

Wires logging, CORS locked to the dashboard origin, RFC 7807 error handlers,
and the Week 1 routers (health, ingestion). New routers are added in roadmap
order. OpenAPI docs self-serve at /docs.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import routes_health, routes_ingestion, routes_kpi, routes_sentiment
from app.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    configure_logging()
    log = get_logger("app")

    app = FastAPI(
        title="Community Management",
        version=__version__,
        description="Intelligent Community Management Analytics Engine.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(routes_health.router)
    app.include_router(routes_ingestion.router)
    app.include_router(routes_kpi.router)
    app.include_router(routes_sentiment.router)

    log.info("app_started", version=__version__, cors_origins=settings.cors_origin_list)
    return app


app = create_app()

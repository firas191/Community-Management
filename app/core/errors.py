"""RFC 7807 problem+json error handling (brief Section 12).

Registers handlers so every error response has media type application/problem+json
with a stable shape: {type, title, status, detail}.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _problem(status_code: int, title: str, detail: str, type_: str = "about:blank") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content={"type": type_, "title": title, "status": status_code, "detail": detail},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(exc.status_code, "HTTP error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(422, "Validation error", str(exc.errors()))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Do not leak internals; log full trace elsewhere via structlog.
        return _problem(500, "Internal server error", "An unexpected error occurred.")

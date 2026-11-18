"""Traduce las excepciones a respuestas ProblemDetails con el código HTTP correcto."""
import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.deps import AuthRequired, Forbidden
from app.domain.exceptions import (
    ConflictException,
    DomainException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)

logger = logging.getLogger("deploymenthub.errors")

PROBLEM_JSON = "application/problem+json"


def problem(status: int, title: str, detail: str | None = None, errors: dict | None = None) -> JSONResponse:
    body: dict = {"type": f"https://httpstatuses.io/{status}", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_\s]+", name) if part)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValidationException)
    async def _validation(request: Request, exc: ValidationException):
        return problem(400, "Datos inválidos", str(exc), exc.errors)

    @app.exception_handler(UnauthorizedException)
    async def _unauthorized(request: Request, exc: UnauthorizedException):
        return problem(401, "No autorizado", str(exc))

    @app.exception_handler(NotFoundException)
    async def _not_found(request: Request, exc: NotFoundException):
        return problem(404, "No encontrado", str(exc))

    @app.exception_handler(ConflictException)
    async def _conflict(request: Request, exc: ConflictException):
        return problem(409, "Conflicto", str(exc))

    @app.exception_handler(DomainException)
    async def _domain(request: Request, exc: DomainException):
        return problem(409, "Regla de negocio", str(exc))

    @app.exception_handler(AuthRequired)
    async def _auth_required(request: Request, exc: AuthRequired):
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        return Response(status_code=403)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError):
        """JSON mal formado, GUID/enum/fecha inválidos o parámetros de consulta incorrectos."""
        errors: dict[str, list[str]] = {}
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            key = ".".join(_pascal(p) if not p.isdigit() else f"[{p}]" for p in loc) or "$"
            errors.setdefault(key, []).append(err.get("msg", "El valor no es válido."))
        return problem(400, "One or more validation errors occurred.", errors=errors)


async def unhandled_exception_response(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no controlado en %s", request.url.path, exc_info=exc)
    # El mensaje de los errores de negocio está pensado para el usuario; el de un 500 no se expone.
    return problem(
        500,
        "Error inesperado",
        "Ocurrió un error inesperado. Intenta de nuevo o contacta al administrador.",
    )

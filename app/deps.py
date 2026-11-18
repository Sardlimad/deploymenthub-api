"""Dependencias de FastAPI: sesión de base de datos, usuario de la sesión y autorización por rol."""
import threading
import time
import uuid
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import new_session
from app.domain import roles as role_names
from app.security import Principal, TokenError, decode_access_token


class AuthRequired(Exception):
    """Sin sesión válida → 401 (sin cuerpo, como JwtBearer)."""


class Forbidden(Exception):
    """Sesión válida sin el rol necesario → 403."""


def optional_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        return decode_access_token(settings, header[7:].strip())
    except TokenError:
        return None


def require_auth(principal: Principal | None = Depends(optional_principal)) -> Principal:
    """Todo exige sesión salvo lo que no declara esta dependencia (login y recuperación)."""
    if principal is None:
        raise AuthRequired()
    return principal


def get_db(principal: Principal | None = Depends(optional_principal)) -> Iterator[Session]:
    # El usuario de la sesión se guarda en la sesión de base de datos para sellar la auditoría (created_by...).
    db = new_session(principal.id if principal else None)
    try:
        yield db
    finally:
        db.close()


def _require_roles(*allowed: str):
    def dependency(principal: Principal = Depends(require_auth)) -> Principal:
        if principal.role not in allowed:
            raise Forbidden()
        return principal

    return dependency


# Políticas por rol (ADMIN puede todo).
require_admin = _require_roles(role_names.ADMIN)  # Catálogos, usuarios y roles.
require_deployer = _require_roles(role_names.ADMIN, role_names.DEVELOPER)  # Armar paquetes y crear/enviar/cancelar solicitudes.
require_operator = _require_roles(role_names.ADMIN, role_names.INFRA)  # Aprobar solicitudes y reportar el resultado.


def current_user_id(principal: Principal = Depends(require_auth)) -> uuid.UUID:
    return principal.id


class _FixedWindowLimiter:
    """Límite de intentos en login y recuperación: 10 por minuto por IP (en memoria, por proceso)."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self._window:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            if len(self._hits) > 10_000:  # evita crecer sin límite
                self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self._window}
            return count <= self._limit


auth_limiter = _FixedWindowLimiter(limit=10, window_seconds=60)


def auth_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    if not auth_limiter.check(ip):
        raise HTTPException(status_code=429)


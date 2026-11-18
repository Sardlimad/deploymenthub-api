"""Contraseñas (bcrypt), tokens JWT de sesión y la aserción firmada de KRUD."""
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt.algorithms import ECAlgorithm

from app.config import Settings
from app.domain import roles as role_names

BCRYPT_WORK_FACTOR = 11
_BCRYPT_MAX_BYTES = 72  # bcrypt solo mira los primeros 72 bytes; BCrypt.Net los trunca en silencio.


def _prepare(value: str) -> bytes:
    return value.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(value: str) -> str:
    return bcrypt.hashpw(_prepare(value), bcrypt.gensalt(BCRYPT_WORK_FACTOR)).decode("ascii")


def verify_password(value: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(value), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # Un hash corrupto equivale a credenciales inválidas, no a un error 500.
        return False


def generate_numeric_code(length: int = 6) -> str:
    return str(secrets.randbelow(10 ** length)).zfill(length)


@dataclass(frozen=True)
class Principal:
    """Usuario de la sesión, tal como viene en el token."""

    id: uuid.UUID
    email: str
    name: str
    role: str


class TokenError(Exception):
    pass


def create_access_token(settings: Settings, user) -> tuple[str, datetime]:
    """Genera el token de acceso. El usuario debe venir con su rol cargado."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_expiration_minutes)
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": role_names.normalize(user.role.name),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
    }
    return jwt.encode(claims, settings.jwt_key, algorithm="HS256"), expires_at


def decode_access_token(settings: Settings, token: str) -> Principal:
    try:
        data = jwt.decode(
            token,
            settings.jwt_key,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=60,
            options={"require": ["exp", "sub"]},
        )
        return Principal(
            id=uuid.UUID(str(data["sub"])),
            email=str(data.get("email", "")),
            name=str(data.get("name", "")),
            role=str(data.get("role", "")),
        )
    except (jwt.PyJWTError, ValueError) as ex:
        raise TokenError(str(ex)) from ex


# ----------------------------------------------------------------------------------------------------------
# KRUD (asistente transversal): DeploymentHub firma al usuario de la sesión con una aserción corta ES256
# y KRUD la verifica con la clave pública registrada. Sin KRUD_PRIVATE_JWK el firmador está apagado.
# ----------------------------------------------------------------------------------------------------------

class KrudPermissions:
    DEPLOY = "deployhub.deploy"
    OPERATE = "deployhub.operate"
    ADMIN = "deployhub.admin"


def krud_permissions_for(role: str | None) -> list[str]:
    """Capacidades por rol, con las mismas reglas que los permisos de la API:
    Deployer = ADMIN + DEVELOPER, Operator = ADMIN + INFRA, Admin = ADMIN."""
    if not role:
        return []
    permissions = [f"role:{role}"]
    if role in (role_names.ADMIN, role_names.DEVELOPER):
        permissions.append(KrudPermissions.DEPLOY)
    if role in (role_names.ADMIN, role_names.INFRA):
        permissions.append(KrudPermissions.OPERATE)
    if role == role_names.ADMIN:
        permissions.append(KrudPermissions.ADMIN)
    return permissions


class KrudAssertionSigner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._key = None
        self._kid: str | None = None
        if not settings.krud_enabled:
            return

        jwk = json.loads(settings.krud_private_jwk)
        if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or not jwk.get("d"):
            raise RuntimeError("KRUD_PRIVATE_JWK debe ser una clave privada EC P-256 (ES256) con su parte «d».")
        self._key = ECAlgorithm.from_jwk(json.dumps(jwk))
        self._kid = jwk.get("kid")

    @property
    def enabled(self) -> bool:
        return self._key is not None

    def sign(self, principal: Principal) -> str:
        if self._key is None:
            raise RuntimeError("El firmador de KRUD no está configurado.")

        # La identidad sale SIEMPRE de la sesión validada, nunca de la petición.
        now = datetime.now(timezone.utc)
        lifetime = min(max(self._settings.krud_lifetime_seconds, 10), 120)
        subject = str(principal.id)
        claims = {
            "iss": self._settings.krud_issuer,
            "aud": self._settings.krud_audience,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=lifetime),
            "sub": subject,
            "jti": uuid.uuid4().hex,
            "userId": subject,
            "name": principal.name or "Usuario",
            # KRUD filtra el catálogo (pantallas, artículos y guías) con estos permisos.
            "permissions": krud_permissions_for(principal.role),
        }
        headers = {"kid": self._kid} if self._kid else None
        return jwt.encode(claims, self._key, algorithm="ES256", headers=headers)

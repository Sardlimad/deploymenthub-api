"""Inicio de sesión, usuario actual, cambio de contraseña y recuperación por código."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import mappers
from app import repositories as repo
from app.config import Settings
from app.domain.exceptions import UnauthorizedException, ValidationException
from app.models import User
from app.notifications.email import EmailSender
from app.schemas import (
    AuthUserDto,
    ChangePasswordBody,
    LoginBody,
    LoginResultDto,
    RequestRecoveryBody,
    ResetPasswordBody,
    VerifyRecoveryBody,
)
from app.security import create_access_token, generate_numeric_code, hash_password, verify_password
from app.validation import Validator

# Mismo mensaje para correo inexistente y contraseña errónea: no revela qué cuentas existen.
INVALID_CREDENTIALS = "Correo o contraseña incorrectos."

CODE_LENGTH = 6
CODE_LIFETIME = timedelta(minutes=15)
INVALID_CODE = "El código no es válido o ya venció. Solicita uno nuevo."
INVALID_SESSION = "La sesión no es válida."


def login(db: Session, settings: Settings, body: LoginBody) -> LoginResultDto:
    v = Validator()
    v.not_empty("Email", body.email)
    v.email("Email", body.email, "Indica un correo válido.")
    v.not_empty("Password", body.password, "Indica la contraseña.")
    v.raise_if_invalid()

    now = datetime.now(timezone.utc)
    user = repo.get_user_by_email(db, body.email)
    if user is None or not user.is_active:
        raise UnauthorizedException(INVALID_CREDENTIALS)

    if user.is_locked_out(now):
        raise UnauthorizedException("La cuenta está bloqueada por intentos fallidos. Intenta de nuevo en unos minutos.")

    if user.password_hash is None:
        raise UnauthorizedException("Aún no has definido tu contraseña. Usa «¿Olvidaste tu contraseña?» para crearla.")

    if not verify_password(body.password, user.password_hash):
        user.register_failed_login(now)
        db.commit()
        raise UnauthorizedException(INVALID_CREDENTIALS)

    user.register_successful_login(now)
    db.commit()

    token, expires_at = create_access_token(settings, user)
    return LoginResultDto(access_token=token, expires_at=expires_at, user=mappers.auth_user_dto(user))


def get_current_user(db: Session, user_id: uuid.UUID | None) -> AuthUserDto:
    if user_id is None:
        raise UnauthorizedException(INVALID_SESSION)
    user = repo.get_user(db, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedException(INVALID_SESSION)
    return mappers.auth_user_dto(user)


def change_password(db: Session, user_id: uuid.UUID | None, body: ChangePasswordBody) -> None:
    v = Validator()
    v.not_empty("CurrentPassword", body.current_password, "Indica tu contraseña actual.")
    v.strong_password("NewPassword", body.new_password)
    if body.new_password == body.current_password:
        v.add("NewPassword", "La nueva contraseña debe ser distinta de la actual.")
    v.raise_if_invalid()

    if user_id is None:
        raise UnauthorizedException(INVALID_SESSION)
    user = repo.get_user(db, user_id)
    if user is None:
        raise UnauthorizedException(INVALID_SESSION)

    if user.password_hash is None or not verify_password(body.current_password, user.password_hash):
        raise ValidationException({"CurrentPassword": ["La contraseña actual no es correcta."]})

    user.set_password_hash(hash_password(body.new_password))
    db.commit()


# Recuperación en tres pasos, igual que la pantalla: pedir código → verificarlo → definir contraseña.
# También sirve para que un usuario nuevo (sin contraseña) cree la suya.

def request_recovery(db: Session, email_sender: EmailSender, body: RequestRecoveryBody) -> None:
    v = Validator()
    v.not_empty("Email", body.email)
    v.email("Email", body.email, "Indica un correo válido.")
    v.raise_if_invalid()

    user = repo.get_user_by_email(db, body.email)
    # Si el correo no existe se responde igual que si existiera, para no revelar cuentas.
    if user is None or not user.is_active:
        return

    code = generate_numeric_code(CODE_LENGTH)
    user.start_password_reset(hash_password(code), datetime.now(timezone.utc) + CODE_LIFETIME)
    db.commit()

    minutes = int(CODE_LIFETIME.total_seconds() // 60)
    email_sender.send_in_background(
        user.email,
        "DeploymentHub: código para restablecer tu contraseña",
        f"Hola {user.name}:\n\nTu código es {code}. Vence en {minutes} minutos.\n\n"
        "Si no lo pediste, ignora este correo; tu contraseña no cambia.",
    )


def _verify_code(db: Session, email: str, code: str) -> User:
    """Comprueba el código y descuenta un intento si es incorrecto."""
    user = repo.get_user_by_email(db, email)
    if user is None or not user.is_active or not user.has_active_password_reset(datetime.now(timezone.utc)):
        raise ValidationException(INVALID_CODE)

    if not verify_password(code, user.password_reset_code_hash):
        user.register_failed_reset_attempt()
        db.commit()
        raise ValidationException(INVALID_CODE)

    return user


def verify_recovery_code(db: Session, body: VerifyRecoveryBody) -> None:
    v = Validator()
    v.not_empty("Email", body.email)
    v.email("Email", body.email)
    v.not_empty("Code", body.code)
    v.exact_len("Code", body.code, CODE_LENGTH, "El código tiene 6 dígitos.")
    v.raise_if_invalid()
    _verify_code(db, body.email, body.code)


def reset_password(db: Session, body: ResetPasswordBody) -> None:
    v = Validator()
    v.not_empty("Email", body.email)
    v.email("Email", body.email)
    v.not_empty("Code", body.code)
    v.exact_len("Code", body.code, CODE_LENGTH, "El código tiene 6 dígitos.")
    v.strong_password("Password", body.password)
    v.raise_if_invalid()

    user = _verify_code(db, body.email, body.code)
    # set_password_hash también invalida el código y desbloquea la cuenta.
    user.set_password_hash(hash_password(body.password))
    db.commit()

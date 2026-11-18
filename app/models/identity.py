import uuid
from datetime import datetime, timedelta

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.exceptions import DomainException
from app.models.base import Entity

_ACTIVE = text("is_deleted = false")


class Role(Entity):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.is_active = True

    def update(self, name: str) -> None:
        self.name = name

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


class User(Entity):
    __tablename__ = "users"
    __table_args__ = (Index("ux_users_email", "email", unique=True, postgresql_where=_ACTIVE),)

    MAX_FAILED_LOGINS = 5
    MAX_RESET_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)

    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(150))
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    role: Mapped[Role] = relationship()

    # Autenticación. Un usuario sin password_hash no puede entrar hasta definir su contraseña
    # con la recuperación por código.
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lockout_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Recuperación de contraseña: se guarda el hash del código, nunca el código.
    password_reset_code_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_reset_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __init__(self, name: str, email: str, role_id: uuid.UUID) -> None:
        super().__init__()
        self.name = name
        self.email = self.normalize_email(email)
        self.role_id = role_id
        self.is_active = True
        self.password_hash = None
        self.failed_login_attempts = 0
        self.lockout_ends_at = None
        self.last_login_at = None
        self.password_reset_code_hash = None
        self.password_reset_expires_at = None
        self.password_reset_attempts = 0

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    def update(self, name: str, email: str, role_id: uuid.UUID) -> None:
        self.name = name
        self.email = self.normalize_email(email)
        self.role_id = role_id

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def is_locked_out(self, now: datetime) -> bool:
        return self.lockout_ends_at is not None and self.lockout_ends_at > now

    def set_password_hash(self, password_hash: str) -> None:
        self.password_hash = password_hash
        self.failed_login_attempts = 0
        self.lockout_ends_at = None
        self.clear_password_reset()

    def register_successful_login(self, now: datetime) -> None:
        self.failed_login_attempts = 0
        self.lockout_ends_at = None
        self.last_login_at = now

    def register_failed_login(self, now: datetime) -> None:
        """Tras MAX_FAILED_LOGINS intentos fallidos la cuenta se bloquea un tiempo."""
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= self.MAX_FAILED_LOGINS:
            self.lockout_ends_at = now + self.LOCKOUT_DURATION
            self.failed_login_attempts = 0

    def start_password_reset(self, code_hash: str, expires_at: datetime) -> None:
        self.password_reset_code_hash = code_hash
        self.password_reset_expires_at = expires_at
        self.password_reset_attempts = 0

    def has_active_password_reset(self, now: datetime) -> bool:
        """Hay un código de recuperación vigente y con intentos disponibles."""
        return (
            self.password_reset_code_hash is not None
            and self.password_reset_expires_at is not None
            and self.password_reset_expires_at > now
            and (self.password_reset_attempts or 0) < self.MAX_RESET_ATTEMPTS
        )

    def register_failed_reset_attempt(self) -> None:
        if self.password_reset_code_hash is None:
            raise DomainException("No hay una recuperación de contraseña en curso.")
        self.password_reset_attempts = (self.password_reset_attempts or 0) + 1

    def clear_password_reset(self) -> None:
        self.password_reset_code_hash = None
        self.password_reset_expires_at = None
        self.password_reset_attempts = 0

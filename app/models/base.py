import uuid
from datetime import datetime, timezone

from enum import IntEnum

from sqlalchemy import Boolean, DateTime, Integer, TypeDecorator, Uuid, false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMPTY_GUID = uuid.UUID(int=0)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntEnumType(TypeDecorator):
    """Guarda un IntEnum como entero (igual que la base de datos original) y lo devuelve como enum."""

    impl = Integer
    cache_ok = True

    def __init__(self, enum_class: type[IntEnum]) -> None:
        super().__init__()
        self.enum_class = enum_class

    def process_bind_param(self, value, dialect):
        return None if value is None else int(self.enum_class(value))

    def process_result_value(self, value, dialect):
        return None if value is None else self.enum_class(value)


class Base(DeclarativeBase):
    pass


class Entity(Base):
    """Base de todas las entidades. El borrado es lógico (is_deleted): el historial de despliegues se conserva."""

    __abstract__ = True

    # Los Id los genera el dominio al construir la entidad, no la base de datos.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.is_deleted = False

    def mark_as_deleted(self) -> None:
        self.is_deleted = True


class AuditEntity(Entity):
    """created_at/created_by/updated_at/updated_by se llenan solos al guardar (ver models/events.py)."""

    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, default=EMPTY_GUID)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    def __init__(self) -> None:
        super().__init__()
        self.created_at = utcnow()
        self.created_by = EMPTY_GUID

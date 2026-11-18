"""Casos de uso de roles y usuarios (solo ADMIN)."""
import uuid

from sqlalchemy.orm import Session

from app import mappers
from app import repositories as repo
from app.domain.exceptions import ConflictException, NotFoundException
from app.models import Role, User
from app.schemas import RoleBody, UserBody
from app.security import hash_password
from app.validation import Validator


# ----------------------------------------------------------------------------------------------- roles

def list_roles(db: Session):
    return [mappers.role_dto(r) for r in repo.list_roles(db)]


def get_role(db: Session, id: uuid.UUID):
    role = repo.get_role(db, id)
    if role is None:
        raise NotFoundException("Rol no encontrado.")
    return mappers.role_dto(role)


def create_role(db: Session, body: RoleBody) -> uuid.UUID:
    v = Validator()
    v.not_empty("Name", body.name)
    v.max_len("Name", body.name, 100)
    v.raise_if_invalid()

    if repo.get_role_by_name(db, body.name) is not None:
        raise ConflictException("El rol ya existe.")
    role = Role(body.name.strip())
    db.add(role)
    db.commit()
    return role.id


def delete_role(db: Session, id: uuid.UUID) -> None:
    role = repo.get_role(db, id)
    if role is None:
        raise NotFoundException("No existe el rol.")
    if repo.role_has_users(db, role.id):
        raise ConflictException("Hay usuarios con este rol. Cámbialos de rol antes de borrarlo.")
    role.mark_as_deleted()
    db.commit()


# --------------------------------------------------------------------------------------------- usuarios

def list_users(db: Session):
    return [mappers.user_dto(u) for u in repo.list_users(db)]


def get_user(db: Session, id: uuid.UUID):
    user = repo.get_user(db, id)
    if user is None:
        raise NotFoundException("Usuario no encontrado.")
    return mappers.user_dto(user)


def _validate_user(body: UserBody) -> None:
    v = Validator()
    v.not_empty("Name", body.name)
    v.max_len("Name", body.name, 150)
    v.not_empty("Email", body.email)
    v.email("Email", body.email)
    v.max_len("Email", body.email, 150)
    v.not_empty("RoleId", body.role_id)
    if body.password is not None and body.password.strip():
        v.strong_password("Password", body.password)
    v.raise_if_invalid()


def create_user(db: Session, body: UserBody) -> uuid.UUID:
    """Password es opcional: si no se indica, el usuario define la suya con la recuperación por código."""
    _validate_user(body)
    if repo.get_user_by_email(db, body.email) is not None:
        raise ConflictException("El correo ya está registrado.")
    if repo.get_role(db, body.role_id) is None:
        raise NotFoundException("No existe el rol.")

    user = User(body.name, body.email, body.role_id)
    if body.password is not None and body.password.strip():
        user.set_password_hash(hash_password(body.password))
    db.add(user)
    db.commit()
    return user.id


def update_user(db: Session, id: uuid.UUID, body: UserBody, current_user_id: uuid.UUID | None) -> None:
    _validate_user(body)
    user = repo.get_user(db, id)
    if user is None:
        raise NotFoundException("No existe el usuario.")
    same_email = repo.get_user_by_email(db, body.email)
    if same_email is not None and same_email.id != user.id:
        raise ConflictException("El correo ya está registrado.")
    if repo.get_role(db, body.role_id) is None:
        raise NotFoundException("No existe el rol.")
    if not body.is_active and user.id == current_user_id:
        raise ConflictException("No puedes desactivar tu propio usuario.")

    user.update(body.name, body.email, body.role_id)
    user.activate() if body.is_active else user.deactivate()
    # Opcional: si se indica, el administrador restablece la contraseña del usuario.
    if body.password is not None and body.password.strip():
        user.set_password_hash(hash_password(body.password))
    db.commit()


def delete_user(db: Session, id: uuid.UUID) -> None:
    user = repo.get_user(db, id)
    if user is None:
        raise NotFoundException("No existe el usuario.")
    user.mark_as_deleted()
    db.commit()

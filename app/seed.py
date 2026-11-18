"""Al arrancar garantiza que existan los roles ADMIN, INFRA y DEVELOPER (respeta los nombres en español que ya
existan) y, si no hay ningún administrador activo, crea uno con SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD.

La contraseña del administrador inicial se configura fuera del repositorio (variables de entorno o .env).
"""
import logging

from sqlalchemy.orm import Session

from app import repositories as repo
from app.config import Settings
from app.domain import roles as role_names
from app.models import Role, User
from app.security import hash_password

logger = logging.getLogger("deploymenthub.seed")


def seed_identity(db: Session, settings: Settings) -> None:
    roles = repo.list_roles(db)

    for code in role_names.ALL:
        if any(role_names.normalize(r.name) == code for r in roles):
            continue
        role = Role(code)
        db.add(role)
        roles.append(role)
        logger.info("Rol %s creado.", code)
    db.commit()

    users = repo.list_users(db)
    if any(u.is_active and role_names.normalize(u.role.name) == role_names.ADMIN for u in users):
        return

    email = settings.seed_admin_email.strip()
    password = settings.seed_admin_password
    if not email or not password.strip():
        logger.warning(
            "No hay ningún administrador activo. Configura SEED_ADMIN_EMAIL y SEED_ADMIN_PASSWORD para crearlo al arrancar."
        )
        return

    admin_role = next(r for r in roles if role_names.normalize(r.name) == role_names.ADMIN)
    existing = repo.get_user_by_email(db, email)

    if existing is not None:
        # El correo ya existe: se promueve a administrador sin cambiar su contraseña si ya tiene una.
        existing.update(existing.name, existing.email, admin_role.id)
        existing.activate()
        if existing.password_hash is None:
            existing.set_password_hash(hash_password(password))
    else:
        admin = User("Administrador", email, admin_role.id)
        admin.set_password_hash(hash_password(password))
        db.add(admin)

    db.commit()
    logger.info("Administrador inicial %s listo.", email)

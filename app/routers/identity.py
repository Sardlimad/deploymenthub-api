"""Usuarios y roles: solo ADMIN."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import current_user_id, get_db, require_admin
from app.routers import created, no_content
from app.schemas import RoleBody, RoleDto, UserBody, UserDto
from app.services import identity as service

roles = APIRouter(prefix="/api/roles", tags=["Roles"], dependencies=[Depends(require_admin)])
users = APIRouter(prefix="/api/users", tags=["Users"], dependencies=[Depends(require_admin)])


@roles.get("", response_model=list[RoleDto])
def list_roles(db: Session = Depends(get_db)):
    return service.list_roles(db)


@roles.get("/{id}", response_model=RoleDto)
def get_role(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_role(db, id)


@roles.post("", status_code=201, response_model=uuid.UUID)
def create_role(body: RoleBody, db: Session = Depends(get_db)):
    id = service.create_role(db, body)
    return created(id, f"/api/roles/{id}")


@roles.delete("/{id}", status_code=204)
def delete_role(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_role(db, id)
    return no_content()


@users.get("", response_model=list[UserDto])
def list_users(db: Session = Depends(get_db)):
    return service.list_users(db)


@users.get("/{id}", response_model=UserDto)
def get_user(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_user(db, id)


@users.post("", status_code=201, response_model=uuid.UUID)
def create_user(body: UserBody, db: Session = Depends(get_db)):
    id = service.create_user(db, body)
    return created(id, f"/api/users/{id}")


@users.put("/{id}", status_code=204)
def update_user(id: uuid.UUID, body: UserBody, db: Session = Depends(get_db), me=Depends(current_user_id)):
    service.update_user(db, id, body, me)
    return no_content()


@users.delete("/{id}", status_code=204)
def delete_user(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_user(db, id)
    return no_content()


all_routers = [roles, users]

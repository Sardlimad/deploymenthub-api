"""Catálogos. Lectura: cualquier usuario con sesión. Escritura: solo ADMIN."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import repositories as repo
from app.deps import get_db, require_admin, require_auth
from app.domain.enums import ProductArtifactType
from app.domain.exceptions import ValidationException
from app.routers import created, no_content
from app.schemas import (
    ClientBody,
    ClientDto,
    EnvironmentBody,
    EnvironmentDto,
    InstallationBody,
    InstallationDto,
    InstallationStatusDto,
    ProductArtifactBody,
    ProductArtifactDto,
    ProductBody,
    ProductDto,
    ProductEnvironmentBody,
    ProductEnvironmentDto,
    parse_enum,
)
from app.services import catalog as service

auth = [Depends(require_auth)]
admin = [Depends(require_admin)]

# ------------------------------------------------------------------------------------------------ clientes
clients = APIRouter(prefix="/api/clients", tags=["Clients"], dependencies=auth)


@clients.get("", response_model=list[ClientDto])
def list_clients(db: Session = Depends(get_db)):
    return service.list_clients(db)


@clients.get("/{id}", response_model=ClientDto)
def get_client(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_client(db, id)


@clients.post("", status_code=201, response_model=uuid.UUID, dependencies=admin)
def create_client(body: ClientBody, db: Session = Depends(get_db)):
    id = service.create_client(db, body)
    return created(id, f"/api/clients/{id}")


@clients.put("/{id}", status_code=204, dependencies=admin)
def update_client(id: uuid.UUID, body: ClientBody, db: Session = Depends(get_db)):
    service.update_client(db, id, body)
    return no_content()


@clients.delete("/{id}", status_code=204, dependencies=admin)
def delete_client(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_client(db, id)
    return no_content()


# ---------------------------------------------------------------------------------------------- ambientes
environments = APIRouter(prefix="/api/environments", tags=["Environments"], dependencies=auth)


@environments.get("", response_model=list[EnvironmentDto])
def list_environments(db: Session = Depends(get_db)):
    return service.list_environments(db)


@environments.get("/{id}", response_model=EnvironmentDto)
def get_environment(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_environment(db, id)


@environments.post("", status_code=201, response_model=uuid.UUID, dependencies=admin)
def create_environment(body: EnvironmentBody, db: Session = Depends(get_db)):
    id = service.create_environment(db, body)
    return created(id, f"/api/environments/{id}")


@environments.put("/{id}", status_code=204, dependencies=admin)
def update_environment(id: uuid.UUID, body: EnvironmentBody, db: Session = Depends(get_db)):
    service.update_environment(db, id, body)
    return no_content()


@environments.delete("/{id}", status_code=204, dependencies=admin)
def delete_environment(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_environment(db, id)
    return no_content()


# ----------------------------------------------------------------------------------------------- productos
products = APIRouter(prefix="/api/products", tags=["Products"], dependencies=auth)


@products.get("", response_model=list[ProductDto])
def list_products(db: Session = Depends(get_db)):
    return service.list_products(db)


@products.get("/{id}", response_model=ProductDto)
def get_product(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_product(db, id)


@products.post("", status_code=201, response_model=uuid.UUID, dependencies=admin)
def create_product(body: ProductBody, db: Session = Depends(get_db)):
    id = service.create_product(db, body)
    return created(id, f"/api/products/{id}")


@products.put("/{id}", status_code=204, dependencies=admin)
def update_product(id: uuid.UUID, body: ProductBody, db: Session = Depends(get_db)):
    service.update_product(db, id, body)
    return no_content()


@products.delete("/{id}", status_code=204, dependencies=admin)
def delete_product(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_product(db, id)
    return no_content()


@products.get("/{id}/environments", response_model=list[ProductEnvironmentDto])
def product_environments(id: uuid.UUID, db: Session = Depends(get_db)):
    """Ambientes en los que existe el producto."""
    return service.list_product_environments(db, id)


@products.get("/{id}/artifacts", response_model=list[ProductArtifactDto])
def product_artifacts(
    id: uuid.UUID,
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Catálogo de artefactos del producto."""
    return service.list_product_artifacts(db, id, _artifact_type(type), search)


def _artifact_type(value: str | None) -> ProductArtifactType | None:
    if value is None or value == "":
        return None
    try:
        return parse_enum(ProductArtifactType, value)
    except ValueError as ex:
        raise ValidationException({"Type": [str(ex)]}) from ex


# ------------------------------------------------------------------------------- ambientes de un producto
product_environments_router = APIRouter(prefix="/api/productenvironments", tags=["ProductEnvironments"], dependencies=auth)


@product_environments_router.get("/{id}", response_model=ProductEnvironmentDto)
def get_product_environment(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_product_environment(db, id)


@product_environments_router.post("", status_code=201, response_model=uuid.UUID, dependencies=admin)
def create_product_environment(body: ProductEnvironmentBody, db: Session = Depends(get_db)):
    id = service.create_product_environment(db, body)
    return created(id, f"/api/productenvironments/{id}")


@product_environments_router.put("/{id}", status_code=204, dependencies=admin)
def update_product_environment(id: uuid.UUID, body: ProductEnvironmentBody, db: Session = Depends(get_db)):
    service.update_product_environment(db, id, body)
    return no_content()


@product_environments_router.delete("/{id}", status_code=204, dependencies=admin)
def delete_product_environment(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_product_environment(db, id)
    return no_content()


# ------------------------------------------------------------------------------------ artefactos de catálogo
product_artifacts_router = APIRouter(prefix="/api/productartifacts", tags=["ProductArtifacts"], dependencies=auth)


@product_artifacts_router.get("/{id}", response_model=ProductArtifactDto)
def get_product_artifact(id: uuid.UUID, db: Session = Depends(get_db)):
    """Registro manual del catálogo. El listado por producto está en GET api/products/{id}/artifacts."""
    return service.get_product_artifact(db, id)


@product_artifacts_router.post("", status_code=201, response_model=uuid.UUID, dependencies=admin)
def create_product_artifact(body: ProductArtifactBody, db: Session = Depends(get_db)):
    id = service.create_product_artifact(db, body)
    return created(id, f"/api/productartifacts/{id}")


@product_artifacts_router.put("/{id}", status_code=204, dependencies=admin)
def update_product_artifact(id: uuid.UUID, body: ProductArtifactBody, db: Session = Depends(get_db)):
    service.update_product_artifact(db, id, body)
    return no_content()


@product_artifacts_router.delete("/{id}", status_code=204, dependencies=admin)
def delete_product_artifact(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_product_artifact(db, id)
    return no_content()


# ------------------------------------------------------------------------------------------- instalaciones
installations = APIRouter(prefix="/api/installations", tags=["Installations"], dependencies=auth)


@installations.get("", response_model=list[InstallationStatusDto])
def list_installations(
    client_id: uuid.UUID | None = Query(default=None, alias="clientId"),
    product_id: uuid.UUID | None = Query(default=None, alias="productId"),
    environment_id: uuid.UUID | None = Query(default=None, alias="environmentId"),
    only_outdated: bool = Query(default=False, alias="onlyOutdated"),
    db: Session = Depends(get_db),
):
    """Estado de versión por instalación. onlyOutdated=true devuelve solo las que necesitan actualización."""
    return service.get_installations_status(
        db, repo.InstallationFilter(client_id, product_id, environment_id, only_outdated)
    )


@installations.get("/{id}", response_model=InstallationDto)
def get_installation(id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_installation(db, id)


@installations.post("", status_code=201, response_model=uuid.UUID, dependencies=admin)
def create_installation(body: InstallationBody, db: Session = Depends(get_db)):
    id = service.create_installation(db, body)
    return created(id, f"/api/installations/{id}")


@installations.put("/{id}", status_code=204, dependencies=admin)
def update_installation(id: uuid.UUID, body: InstallationBody, db: Session = Depends(get_db)):
    service.update_installation(db, id, body)
    return no_content()


@installations.delete("/{id}", status_code=204, dependencies=admin)
def delete_installation(id: uuid.UUID, db: Session = Depends(get_db)):
    service.delete_installation(db, id)
    return no_content()


all_routers = [
    clients, environments, products, product_environments_router, product_artifacts_router, installations,
]

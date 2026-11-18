"""Casos de uso de catálogos: clientes, ambientes, productos, ambientes de producto, artefactos e instalaciones."""
import uuid

from sqlalchemy.orm import Session

from app import mappers
from app import repositories as repo
from app.domain.enums import ProductArtifactType
from app.domain.exceptions import ConflictException, NotFoundException
from app.models import (
    Client,
    ClientProductEnvironment,
    DeploymentEnvironment,
    Product,
    ProductArtifact,
    ProductEnvironment,
)
from app.schemas import (
    ClientBody,
    EnvironmentBody,
    InstallationBody,
    ProductArtifactBody,
    ProductBody,
    ProductEnvironmentBody,
)
from app.validation import Validator


# --------------------------------------------------------------------------------------------- clientes

def _validate_client(body: ClientBody) -> None:
    v = Validator()
    v.not_empty("Code", body.code)
    v.max_len("Code", body.code, 30)
    v.not_empty("Name", body.name)
    v.max_len("Name", body.name, 150)
    v.raise_if_invalid()


def list_clients(db: Session):
    return [mappers.client_dto(c) for c in repo.list_clients(db)]


def get_client(db: Session, id: uuid.UUID):
    client = repo.get_client(db, id)
    if client is None:
        raise NotFoundException("Cliente no encontrado.")
    return mappers.client_dto(client)


def create_client(db: Session, body: ClientBody) -> uuid.UUID:
    _validate_client(body)
    if repo.get_client_by_code(db, body.code) is not None:
        raise ConflictException(f"Ya existe un cliente con el código '{body.code.upper()}'.")
    client = Client(body.name, body.code, body.is_on_premise)
    db.add(client)
    db.commit()
    return client.id


def update_client(db: Session, id: uuid.UUID, body: ClientBody) -> None:
    _validate_client(body)
    client = repo.get_client(db, id)
    if client is None:
        raise NotFoundException("No existe el cliente.")
    same_code = repo.get_client_by_code(db, body.code)
    if same_code is not None and same_code.id != client.id:
        raise ConflictException(f"Ya existe un cliente con el código '{body.code.upper()}'.")
    client.update(body.name, body.code, body.is_on_premise)
    client.activate() if body.is_active else client.deactivate()
    db.commit()


def delete_client(db: Session, id: uuid.UUID) -> None:
    client = repo.get_client(db, id)
    if client is None:
        raise NotFoundException("No existe el cliente.")
    if repo.any_installation_for_client(db, client.id):
        raise ConflictException("El cliente tiene productos contratados. Quítalos o desactiva el cliente.")
    client.mark_as_deleted()
    db.commit()


# -------------------------------------------------------------------------------------------- ambientes

def _validate_environment(body: EnvironmentBody) -> None:
    v = Validator()
    v.not_empty("Code", body.code)
    v.max_len("Code", body.code, 20)
    v.not_empty("Name", body.name)
    v.max_len("Name", body.name, 100)
    v.raise_if_invalid()


def list_environments(db: Session):
    return [mappers.environment_dto(e) for e in repo.list_environments(db)]


def get_environment(db: Session, id: uuid.UUID):
    env = repo.get_environment(db, id)
    if env is None:
        raise NotFoundException("Ambiente no encontrado.")
    return mappers.environment_dto(env)


def create_environment(db: Session, body: EnvironmentBody) -> uuid.UUID:
    _validate_environment(body)
    if repo.get_environment_by_code(db, body.code) is not None:
        raise ConflictException(f"Ya existe un ambiente con el código '{body.code.upper()}'.")
    env = DeploymentEnvironment(body.name, body.code)
    db.add(env)
    db.commit()
    return env.id


def update_environment(db: Session, id: uuid.UUID, body: EnvironmentBody) -> None:
    _validate_environment(body)
    env = repo.get_environment(db, id)
    if env is None:
        raise NotFoundException("No existe el ambiente.")
    same_code = repo.get_environment_by_code(db, body.code)
    if same_code is not None and same_code.id != env.id:
        raise ConflictException(f"Ya existe un ambiente con el código '{body.code.upper()}'.")
    env.update(body.name, body.code)
    env.activate() if body.is_active else env.deactivate()
    db.commit()


def delete_environment(db: Session, id: uuid.UUID) -> None:
    env = repo.get_environment(db, id)
    if env is None:
        raise NotFoundException("No existe el ambiente.")
    if repo.environment_is_used(db, env.id):
        raise ConflictException("Hay productos configurados en este ambiente. Quítalos o desactiva el ambiente.")
    env.mark_as_deleted()
    db.commit()


# ------------------------------------------------------------------------------------------- productos

def _validate_product(body: ProductBody) -> None:
    v = Validator()
    v.not_empty("Code", body.code)
    v.max_len("Code", body.code, 30)
    v.not_empty("Name", body.name)
    v.max_len("Name", body.name, 150)
    v.raise_if_invalid()


def list_products(db: Session):
    return [mappers.product_dto(p) for p in repo.list_products(db)]


def get_product(db: Session, id: uuid.UUID):
    product = repo.get_product(db, id)
    if product is None:
        raise NotFoundException("Producto no encontrado.")
    return mappers.product_dto(product)


def create_product(db: Session, body: ProductBody) -> uuid.UUID:
    _validate_product(body)
    if repo.get_product_by_code(db, body.code) is not None:
        raise ConflictException(f"Ya existe un producto con el código '{body.code.upper()}'.")
    product = Product(body.name, body.code)
    db.add(product)
    db.commit()
    return product.id


def update_product(db: Session, id: uuid.UUID, body: ProductBody) -> None:
    _validate_product(body)
    product = repo.get_product(db, id)
    if product is None:
        raise NotFoundException("No existe el producto.")
    same_code = repo.get_product_by_code(db, body.code)
    if same_code is not None and same_code.id != product.id:
        raise ConflictException(f"Ya existe un producto con el código '{body.code.upper()}'.")
    product.update(body.name, body.code)
    product.activate() if body.is_active else product.deactivate()
    db.commit()


def delete_product(db: Session, id: uuid.UUID) -> None:
    product = repo.get_product(db, id)
    if product is None:
        raise NotFoundException("No existe el producto.")
    if len(product.product_environments) > 0:
        raise ConflictException("El producto tiene ambientes configurados. Quítalos o desactiva el producto.")
    product.mark_as_deleted()
    db.commit()


# ----------------------------------------------------------------------------- ambientes de un producto

def list_product_environments(db: Session, product_id: uuid.UUID):
    return [mappers.product_environment_dto(pe) for pe in repo.list_product_environments(db, product_id)]


def get_product_environment(db: Session, id: uuid.UUID):
    pe = repo.get_product_environment(db, id)
    if pe is None:
        raise NotFoundException("Ambiente de producto no encontrado.")
    return mappers.product_environment_dto(pe)


def create_product_environment(db: Session, body: ProductEnvironmentBody) -> uuid.UUID:
    v = Validator()
    v.not_empty("ProductId", body.product_id)
    v.not_empty("EnvironmentId", body.environment_id)
    v.max_len("BaseUrl", body.base_url, 100)
    v.raise_if_invalid()

    if repo.get_product(db, body.product_id) is None:
        raise NotFoundException("No existe el producto.")
    if repo.get_environment(db, body.environment_id) is None:
        raise NotFoundException("No existe el ambiente.")
    if repo.find_product_environment(db, body.product_id, body.environment_id) is not None:
        raise ConflictException("El producto ya tiene ese ambiente.")

    pe = ProductEnvironment(body.product_id, body.environment_id, body.base_url or "")
    db.add(pe)
    db.commit()
    return pe.id


def update_product_environment(db: Session, id: uuid.UUID, body: ProductEnvironmentBody) -> None:
    v = Validator()
    v.max_len("BaseUrl", body.base_url, 100)
    v.raise_if_invalid()

    pe = repo.get_product_environment(db, id)
    if pe is None:
        raise NotFoundException("No existe el ambiente para este producto.")
    pe.update(body.base_url or "")
    pe.activate() if body.is_active else pe.deactivate()
    db.commit()


def delete_product_environment(db: Session, id: uuid.UUID) -> None:
    pe = repo.get_product_environment(db, id)
    if pe is None:
        raise NotFoundException("No existe el ambiente para este producto.")
    if repo.any_installation_for_product_environment(db, pe.id):
        raise ConflictException("Hay clientes con este producto en este ambiente. Quítalos o desactiva el ambiente.")
    pe.mark_as_deleted()
    db.commit()


# ------------------------------------------------------------------------------- artefactos del catálogo

def _validate_artifact(body: ProductArtifactBody, *, creating: bool) -> None:
    v = Validator()
    if creating:
        v.not_empty("ProductId", body.product_id)
    v.not_empty("Code", body.code)
    v.max_len("Code", body.code, 200)
    v.not_empty("Name", body.name)
    v.max_len("Name", body.name, 200)
    v.not_null("Type", body.type)
    v.max_len("Description", body.description, 500)
    v.max_len("Path", body.path, 500)
    v.raise_if_invalid()


def list_product_artifacts(db: Session, product_id: uuid.UUID, type: ProductArtifactType | None, search: str | None):
    return [mappers.product_artifact_dto(a) for a in repo.list_product_artifacts(db, product_id, type, search)]


def get_product_artifact(db: Session, id: uuid.UUID):
    artifact = repo.get_product_artifact(db, id)
    if artifact is None:
        raise NotFoundException("Artefacto no encontrado.")
    return mappers.product_artifact_dto(artifact)


def create_product_artifact(db: Session, body: ProductArtifactBody) -> uuid.UUID:
    """Registro manual de un artefacto en el catálogo (sin paquete)."""
    _validate_artifact(body, creating=True)
    if repo.get_product(db, body.product_id) is None:
        raise NotFoundException("No existe el producto.")

    existing = repo.find_product_artifact(db, body.product_id, body.type, body.code, body.owner_client_id)
    if existing is not None:
        raise ConflictException(
            "Ya existe la versión general de un artefacto de ese tipo con ese código."
            if body.owner_client_id is None
            else "Ese cliente ya tiene su versión de un artefacto de ese tipo con ese código."
        )

    artifact = ProductArtifact(
        body.product_id, body.code, body.name, body.type, body.description, body.path,
        owner_client_id=body.owner_client_id,
    )
    db.add(artifact)
    db.commit()
    return artifact.id


def update_product_artifact(db: Session, id: uuid.UUID, body: ProductArtifactBody) -> None:
    _validate_artifact(body, creating=False)
    artifact = repo.get_product_artifact(db, id)
    if artifact is None:
        raise NotFoundException("No existe el artefacto.")
    same_key = repo.find_product_artifact(db, artifact.product_id, body.type, body.code, artifact.owner_client_id)
    if same_key is not None and same_key.id != artifact.id:
        raise ConflictException("Ya existe un artefacto de ese tipo con ese código en el producto.")
    artifact.update(body.code, body.name, body.type, body.description, body.path)
    artifact.activate() if body.is_active else artifact.deactivate()
    db.commit()


def delete_product_artifact(db: Session, id: uuid.UUID) -> None:
    artifact = repo.get_product_artifact(db, id)
    if artifact is None:
        raise NotFoundException("No existe el artefacto.")
    if repo.artifact_is_used_in_packages(db, artifact.id):
        raise ConflictException("El artefacto está en paquetes de despliegue. Desactívalo en lugar de borrarlo.")
    artifact.mark_as_deleted()
    db.commit()


# ------------------------------------------------------------------------------------------ instalaciones

def get_installations_status(db: Session, filter: repo.InstallationFilter):
    return mappers.installation_status_dtos(db, filter)


def get_installation(db: Session, id: uuid.UUID):
    installation = repo.get_installation(db, id)
    if installation is None:
        raise NotFoundException("Instalación no encontrada.")
    return mappers.installation_dto(installation)


def create_installation(db: Session, body: InstallationBody) -> uuid.UUID:
    """Registra que un cliente tiene contratado un producto en un ambiente."""
    v = Validator()
    v.not_empty("ClientId", body.client_id)
    v.not_empty("ProductEnvironmentId", body.product_environment_id)
    v.max_len("BaseUrl", body.base_url, 500)
    v.raise_if_invalid()

    if repo.get_client(db, body.client_id) is None:
        raise NotFoundException("No existe el cliente.")
    if repo.get_product_environment(db, body.product_environment_id) is None:
        raise NotFoundException("No existe el ambiente del producto.")
    if repo.installation_exists(db, body.client_id, body.product_environment_id):
        raise ConflictException("El cliente ya tiene ese producto en ese ambiente.")

    installation = ClientProductEnvironment(body.client_id, body.product_environment_id, body.base_url)
    db.add(installation)
    db.commit()
    return installation.id


def update_installation(db: Session, id: uuid.UUID, body: InstallationBody) -> None:
    v = Validator()
    v.max_len("BaseUrl", body.base_url, 500)
    v.raise_if_invalid()

    installation = repo.get_installation(db, id)
    if installation is None:
        raise NotFoundException("No existe la instalación.")
    installation.update(body.base_url)
    installation.activate() if body.is_active else installation.deactivate()
    db.commit()


def delete_installation(db: Session, id: uuid.UUID) -> None:
    installation = repo.get_installation(db, id)
    if installation is None:
        raise NotFoundException("No existe la instalación.")
    if repo.installation_is_used_in_requests(db, installation.id):
        raise ConflictException("La instalación tiene despliegues registrados. Desactívala en lugar de borrarla.")
    installation.mark_as_deleted()
    db.commit()

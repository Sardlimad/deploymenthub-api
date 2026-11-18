"""Casos de uso de paquetes de despliegue y de los artefactos dentro de un paquete."""
import uuid

from sqlalchemy.orm import Session

from app import mappers
from app import repositories as repo
from app.domain.enums import ArtifactChangeType, ProductArtifactType
from app.domain.exceptions import ConflictException, NotFoundException
from app.models import DeploymentPackage, DeploymentPackageArtifact, PackageSource, ProductArtifact
from app.realtime import EventTypes, RealtimeEvent, hub
from app.schemas import (
    DeploymentPackageBody,
    PackageArtifactDto,
    PackageArtifactInput,
    UpdatePackageArtifactBody,
)
from app.validation import Validator


def validate_artifact_input(v: Validator, prop: str, a: PackageArtifactInput | None) -> None:
    if a is None:
        v.not_null(prop, None)
        return
    if a.product_artifact_id is None:
        v.not_null(f"{prop}.Type", a.type, "Indica el tipo del artefacto o elige uno del catálogo.")
        v.not_empty(f"{prop}.Code", a.code, "Indica el código del artefacto o elige uno del catálogo.")
        v.max_len(f"{prop}.Code", a.code, 200)
    v.max_len(f"{prop}.Name", a.name, 200)
    v.max_len(f"{prop}.Path", a.path, 500)
    v.max_len(f"{prop}.Description", a.description, 500)
    if a.execution_order is not None:
        v.greater_than(f"{prop}.ExecutionOrder", a.execution_order, 0)
    v.max_len(f"{prop}.Notes", a.notes, 1000)


class PackageArtifactResolver:
    """Decide qué VERSIÓN de cada artefacto lleva el paquete (RN-03 y RN-11):

    - El paquete lleva la versión de su destinatario: la del cliente en un paquete personalizado, la general en uno general.
    - Por código (importador o «agregar por código»): se usa esa versión; si no existe, entra como «Nuevo» para ese destinatario.
    - Si se elige la versión personalizada de A para el cliente B: se usa la versión de B (se crea a partir de la de A si no existía).
    - Si se elige la versión de A para un paquete general: deja de ser personalizada. Si no hay versión general, la de A pasa
      a serlo; si la hay, se usa la general y la de A se desactiva (A recibe la general).

    La interfaz avisa antes de los dos últimos casos.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        # Versiones resueltas en esta misma operación.
        self._resolved: dict[tuple[ProductArtifactType, str, uuid.UUID | None], ProductArtifact] = {}
        self._created: list[ProductArtifact] = []

    @property
    def created_artifacts(self) -> list[ProductArtifact]:
        return self._created

    def add_to_package(self, package: DeploymentPackage, data: PackageArtifactInput) -> DeploymentPackageArtifact:
        artifact, change_type = self._resolve(package, data)
        return package.add_artifact(artifact, change_type, data.execution_order, data.notes)

    def _resolve(self, package: DeploymentPackage, data: PackageArtifactInput) -> tuple[ProductArtifact, ArtifactChangeType]:
        owner = package.custom_client_id

        if data.product_artifact_id is not None:
            selected = repo.get_product_artifact(self._db, data.product_artifact_id)
            if selected is None:
                raise NotFoundException("No existe el artefacto del catálogo.")

            if selected.belongs_to(owner):
                return self._remember(selected), self._existing_change_type(data.change_type)

            # Se eligió la versión de otro dueño.
            own_version = self._find_version(package.product_id, selected.type, selected.code, owner)
            if own_version is not None:
                if owner is None and selected.is_custom:
                    selected.deactivate()  # el cliente pasa a recibir la versión general
                return own_version, self._existing_change_type(data.change_type)

            if owner is None:
                selected.make_general()  # la versión personalizada pasa a ser la general
                return self._remember(selected), self._existing_change_type(data.change_type)

            copy = selected.create_version_for(owner, package.id)
            self._add_new(copy)
            return copy, ArtifactChangeType.Added

        type_ = data.type
        code = ProductArtifact.normalize_code(data.code)
        version = self._find_version(package.product_id, type_, code, owner)
        if version is not None:
            change = (
                ArtifactChangeType.Added
                if any(version is c for c in self._created)
                else self._existing_change_type(data.change_type)
            )
            return version, change

        if data.change_type == ArtifactChangeType.Removed:
            raise ConflictException(f"No se puede quitar '{code}': no existe esa versión en el catálogo del producto.")

        new_artifact = ProductArtifact(
            package.product_id,
            code,
            data.name if (data.name or "").strip() else code,
            type_,
            data.description,
            data.path,
            introduced_in_package_id=package.id,
            owner_client_id=owner,
        )
        self._add_new(new_artifact)
        return new_artifact, ArtifactChangeType.Added

    def _find_version(
        self, product_id: uuid.UUID, type_: ProductArtifactType, code: str, owner: uuid.UUID | None
    ) -> ProductArtifact | None:
        cached = self._resolved.get((type_, code, owner))
        if cached is not None:
            return cached
        found = repo.find_product_artifact(self._db, product_id, type_, code, owner)
        return self._remember(found) if found is not None else None

    def _remember(self, artifact: ProductArtifact) -> ProductArtifact:
        self._resolved[(artifact.type, artifact.code, artifact.owner_client_id)] = artifact
        return artifact

    def _add_new(self, artifact: ProductArtifact) -> None:
        self._db.add(artifact)
        self._created.append(artifact)
        self._remember(artifact)

    @staticmethod
    def _existing_change_type(requested: ArtifactChangeType | None) -> ArtifactChangeType:
        if requested == ArtifactChangeType.Added:
            raise ConflictException("El artefacto ya existe en el catálogo; no puede marcarse como nuevo.")
        return requested or ArtifactChangeType.Modified

    def catalog_events(self, package: DeploymentPackage) -> list[RealtimeEvent]:
        """Eventos en tiempo real para los artefactos que entraron al catálogo."""
        return [
            RealtimeEvent(
                EventTypes.ARTIFACT_ADDED_TO_CATALOG,
                None,
                {
                    "productId": a.product_id,
                    "packageId": package.id,
                    "artifact": mappers.product_artifact_dto(a),
                },
            )
            for a in self._created
        ]


def _retire_if_only_used_here(db: Session, removed: DeploymentPackageArtifact, package_id: uuid.UUID) -> None:
    """Si un artefacto entró al catálogo con este paquete y se quita del paquete antes de enviarlo,
    fue un error de armado: se retira del catálogo, salvo que ya lo use otro paquete."""
    if not removed.is_new or not removed.product_artifact.was_introduced_by(package_id):
        return
    # El artefacto ya no está en este paquete (se quitó de la colección), pero el borrado aún no se escribió:
    # se excluye este paquete de la consulta.
    if repo.artifact_is_used_in_packages(db, removed.product_artifact_id, exclude_package_id=package_id):
        return
    removed.product_artifact.mark_as_deleted()


# ------------------------------------------------------------------------------------------------ paquetes

def _validate_package(body: DeploymentPackageBody, *, creating: bool, id_prop: bool = True) -> None:
    v = Validator()
    if creating:
        v.not_empty("ProductId", body.product_id)
    v.not_empty("Description", body.description)
    v.max_len("Description", body.description, 500)
    v.max_len("RepositoryId", body.repository_id, 200)
    v.max_len("Branch", body.branch, 200)
    v.max_len("CommitId", body.commit_id, 100)
    v.max_len("CommitAuthor", body.commit_author, 200)
    v.max_len("CommitMessage", body.commit_message, 1000)
    v.max_len("PackageUrl", body.package_url, 1000)
    if creating:
        for i, artifact in enumerate(body.artifacts or []):
            validate_artifact_input(v, f"Artifacts[{i}]", artifact)
    v.raise_if_invalid()


def _source(body: DeploymentPackageBody) -> PackageSource:
    return PackageSource(
        body.repository_id, body.branch, body.commit_id, body.commit_author,
        body.commit_message, body.commit_date, body.package_url,
    )


def list_packages(db: Session, product_id: uuid.UUID | None):
    return [mappers.package_dto(p) for p in repo.list_packages(db, product_id)]


def get_package(db: Session, id: uuid.UUID):
    package = repo.get_package(db, id)
    if package is None:
        raise NotFoundException("Paquete de despliegue no encontrado.")
    return mappers.package_dto(package)


def create_package(db: Session, body: DeploymentPackageBody):
    """Crea el paquete con sus artefactos. Los artefactos que no existan en el catálogo del producto
    se agregan al catálogo y quedan marcados como nuevos (is_new = true)."""
    _validate_package(body, creating=True)
    if repo.get_product(db, body.product_id) is None:
        raise NotFoundException("No existe el producto.")
    if body.custom_client_id is not None and repo.get_client(db, body.custom_client_id) is None:
        raise NotFoundException("No existe el cliente de la actualización personalizada.")

    package = DeploymentPackage(body.product_id, body.description, _source(body), body.custom_client_id)
    db.add(package)

    resolver = PackageArtifactResolver(db)
    for artifact in body.artifacts or []:
        resolver.add_to_package(package, artifact)
    db.commit()

    for event in resolver.catalog_events(package):
        hub.publish(event)

    saved = repo.get_package(db, package.id)
    return mappers.package_dto(saved)


def update_package(db: Session, id: uuid.UUID, body: DeploymentPackageBody) -> None:
    _validate_package(body, creating=False)
    package = repo.get_package(db, id)
    if package is None:
        raise NotFoundException("No existe el paquete de despliegue.")
    if body.custom_client_id is not None and repo.get_client(db, body.custom_client_id) is None:
        raise NotFoundException("No existe el cliente de la actualización personalizada.")

    package.update_info(body.description, _source(body), body.custom_client_id)
    db.commit()


def delete_package(db: Session, id: uuid.UUID) -> None:
    """Borra un paquete que nunca se usó en una solicitud. Los artefactos que entraron al catálogo con este
    paquete y no están en otro paquete también se retiran del catálogo."""
    package = repo.get_package(db, id)
    if package is None:
        raise NotFoundException("No existe el paquete de despliegue.")
    if package.is_locked or repo.package_is_used_in_requests(db, package.id):
        raise ConflictException("El paquete está asociado a solicitudes de despliegue y no se puede borrar.")

    for package_artifact in list(package.artifacts):
        package.remove_artifact(package_artifact.id)
        _retire_if_only_used_here(db, package_artifact, package.id)

    package.mark_as_deleted()
    db.commit()


# -------------------------------------------------------------------------------- artefactos de un paquete

def get_package_artifact(db: Session, package_id: uuid.UUID, package_artifact_id: uuid.UUID) -> PackageArtifactDto:
    package = repo.get_package(db, package_id)
    if package is None:
        raise NotFoundException("Paquete de despliegue no encontrado.")
    package_artifact = next((a for a in package.artifacts if a.id == package_artifact_id), None)
    if package_artifact is None:
        raise NotFoundException("El artefacto no está en este paquete.")
    return mappers.package_artifact_dto(package_artifact)


def add_package_artifact(db: Session, package_id: uuid.UUID, data: PackageArtifactInput) -> PackageArtifactDto:
    """Agrega un artefacto a un paquete; si no existe en el catálogo, entra como nuevo."""
    v = Validator()
    v.not_empty("PackageId", package_id)
    validate_artifact_input(v, "Artifact", data)
    v.raise_if_invalid()

    package = repo.get_package(db, package_id)
    if package is None:
        raise NotFoundException("No existe el paquete de despliegue.")

    resolver = PackageArtifactResolver(db)
    package_artifact = resolver.add_to_package(package, data)
    db.commit()

    for event in resolver.catalog_events(package):
        hub.publish(event)
    return mappers.package_artifact_dto(package_artifact)


def update_package_artifact(
    db: Session, package_id: uuid.UUID, package_artifact_id: uuid.UUID, body: UpdatePackageArtifactBody
) -> None:
    v = Validator()
    v.greater_than("ExecutionOrder", body.execution_order or 0, 0)
    v.max_len("Notes", body.notes, 1000)
    v.raise_if_invalid()

    package = repo.get_package(db, package_id)
    if package is None:
        raise NotFoundException("No existe el paquete de despliegue.")
    package.update_artifact(package_artifact_id, body.execution_order, body.notes)
    db.commit()


def delete_package_artifact(db: Session, package_id: uuid.UUID, package_artifact_id: uuid.UUID) -> None:
    package = repo.get_package(db, package_id)
    if package is None:
        raise NotFoundException("No existe el paquete de despliegue.")
    removed = package.remove_artifact(package_artifact_id)
    _retire_if_only_used_here(db, removed, package.id)
    db.commit()

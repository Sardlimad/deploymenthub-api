"""Consultas a la base. Devuelven entidades rastreadas por la sesión: para modificar basta con cambiar la entidad
y hacer commit. Borrar es lógico: entity.mark_as_deleted() (el filtro de borrados está en models/events.py)."""
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.enums import DeploymentRequestStatus, DeploymentRequestTargetStatus, ProductArtifactType
from app.models import (
    REQUEST_NUMBER_SEQUENCE,
    Client,
    ClientProductEnvironment,
    DeploymentEnvironment,
    DeploymentPackage,
    DeploymentPackageArtifact,
    DeploymentRequest,
    DeploymentRequestTarget,
    Product,
    ProductArtifact,
    ProductEnvironment,
    Role,
    Ticket,
    User,
)


def _like(text_value: str) -> str:
    escaped = text_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --------------------------------------------------------------------------------------------- catálogos

def get_client(db: Session, id: uuid.UUID) -> Client | None:
    return db.scalars(select(Client).where(Client.id == id)).first()


def get_client_by_code(db: Session, code: str) -> Client | None:
    return db.scalars(select(Client).where(Client.code == code.strip().upper())).first()


def list_clients(db: Session) -> list[Client]:
    return list(db.scalars(select(Client).order_by(func.lower(Client.name))))


def get_environment(db: Session, id: uuid.UUID) -> DeploymentEnvironment | None:
    return db.scalars(select(DeploymentEnvironment).where(DeploymentEnvironment.id == id)).first()


def get_environment_by_code(db: Session, code: str) -> DeploymentEnvironment | None:
    return db.scalars(
        select(DeploymentEnvironment).where(DeploymentEnvironment.code == code.strip().upper())
    ).first()


def list_environments(db: Session) -> list[DeploymentEnvironment]:
    return list(db.scalars(select(DeploymentEnvironment).order_by(func.lower(DeploymentEnvironment.name))))


def environment_is_used(db: Session, id: uuid.UUID) -> bool:
    return db.scalar(select(exists().where(ProductEnvironment.deployment_environment_id == id, ProductEnvironment.is_deleted.is_(False)))) or False


_PRODUCT_LOAD = (selectinload(Product.product_environments).joinedload(ProductEnvironment.deployment_environment),)


def get_product(db: Session, id: uuid.UUID) -> Product | None:
    return db.scalars(select(Product).where(Product.id == id).options(*_PRODUCT_LOAD)).first()


def get_product_by_code(db: Session, code: str) -> Product | None:
    return db.scalars(select(Product).where(Product.code == code.strip().upper())).first()


def list_products(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).options(*_PRODUCT_LOAD).order_by(func.lower(Product.name))))


def get_product_environment(db: Session, id: uuid.UUID) -> ProductEnvironment | None:
    return db.scalars(
        select(ProductEnvironment).where(ProductEnvironment.id == id).options(joinedload(ProductEnvironment.deployment_environment))
    ).first()


def find_product_environment(db: Session, product_id: uuid.UUID, environment_id: uuid.UUID) -> ProductEnvironment | None:
    return db.scalars(
        select(ProductEnvironment).where(
            ProductEnvironment.product_id == product_id, ProductEnvironment.deployment_environment_id == environment_id
        )
    ).first()


def list_product_environments(db: Session, product_id: uuid.UUID) -> list[ProductEnvironment]:
    return list(
        db.scalars(
            select(ProductEnvironment)
            .join(ProductEnvironment.deployment_environment)
            .where(ProductEnvironment.product_id == product_id)
            .options(joinedload(ProductEnvironment.deployment_environment))
            .order_by(func.lower(DeploymentEnvironment.name))
        )
    )


# ------------------------------------------------------------------------------------------- instalaciones

_INSTALLATION_LOAD = (
    joinedload(ClientProductEnvironment.client),
    joinedload(ClientProductEnvironment.product_environment).joinedload(ProductEnvironment.product),
    joinedload(ClientProductEnvironment.product_environment).joinedload(ProductEnvironment.deployment_environment),
    joinedload(ClientProductEnvironment.current_package),
)


def get_installation(db: Session, id: uuid.UUID) -> ClientProductEnvironment | None:
    return db.scalars(
        select(ClientProductEnvironment).where(ClientProductEnvironment.id == id).options(*_INSTALLATION_LOAD)
    ).first()


def get_installations(db: Session, ids: Collection[uuid.UUID]) -> list[ClientProductEnvironment]:
    if not ids:
        return []
    return list(
        db.scalars(
            select(ClientProductEnvironment).where(ClientProductEnvironment.id.in_(list(ids))).options(*_INSTALLATION_LOAD)
        ).unique()
    )


def installation_exists(db: Session, client_id: uuid.UUID, product_environment_id: uuid.UUID) -> bool:
    return db.scalar(
        select(
            exists().where(
                ClientProductEnvironment.client_id == client_id,
                ClientProductEnvironment.product_environment_id == product_environment_id,
                ClientProductEnvironment.is_deleted.is_(False),
            )
        )
    ) or False


def any_installation_for_client(db: Session, client_id: uuid.UUID) -> bool:
    return db.scalar(
        select(exists().where(ClientProductEnvironment.client_id == client_id, ClientProductEnvironment.is_deleted.is_(False)))
    ) or False


def any_installation_for_product_environment(db: Session, product_environment_id: uuid.UUID) -> bool:
    return db.scalar(
        select(
            exists().where(
                ClientProductEnvironment.product_environment_id == product_environment_id,
                ClientProductEnvironment.is_deleted.is_(False),
            )
        )
    ) or False


def installation_is_used_in_requests(db: Session, id: uuid.UUID) -> bool:
    return db.scalar(
        select(
            exists().where(
                DeploymentRequestTarget.client_product_environment_id == id,
                DeploymentRequestTarget.is_deleted.is_(False),
            )
        )
    ) or False


@dataclass(frozen=True)
class InstallationFilter:
    client_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    only_outdated: bool = False


@dataclass(frozen=True)
class LatestPackage:
    package_id: uuid.UUID
    description: str
    created_at: object


@dataclass(frozen=True)
class PendingRequest:
    request_id: uuid.UUID
    request_number: int


_IN_FLIGHT_REQUESTS = (DeploymentRequestStatus.Pending, DeploymentRequestStatus.Approved, DeploymentRequestStatus.InProgress)
_WAITING_TARGETS = (
    DeploymentRequestTargetStatus.Pending,
    DeploymentRequestTargetStatus.Scheduled,
    DeploymentRequestTargetStatus.InProgress,
)


def installation_status_data(
    db: Session, filter: InstallationFilter
) -> tuple[list[ClientProductEnvironment], dict[uuid.UUID, LatestPackage], dict[uuid.UUID, PendingRequest]]:
    """Instalaciones filtradas + el último paquete GENERAL aplicado por producto-ambiente + la solicitud pendiente de cada una."""
    query = (
        select(ClientProductEnvironment)
        .join(ClientProductEnvironment.client)
        .join(ClientProductEnvironment.product_environment)
        .join(ProductEnvironment.product)
        .options(*_INSTALLATION_LOAD)
        .order_by(func.lower(Client.name), func.lower(Product.name))
    )
    if filter.client_id:
        query = query.where(ClientProductEnvironment.client_id == filter.client_id)
    if filter.product_id:
        query = query.where(ProductEnvironment.product_id == filter.product_id)
    if filter.environment_id:
        query = query.where(ProductEnvironment.deployment_environment_id == filter.environment_id)

    installations = list(db.scalars(query).unique())
    if not installations:
        return [], {}, {}

    pe_ids = list({i.product_environment_id for i in installations})
    installation_ids = [i.id for i in installations]

    # Último paquete GENERAL aplicado con éxito en cada producto-ambiente (en cualquier cliente).
    # Los personalizados no cuentan: solo aplican a su cliente y no son una versión del producto.
    applied = db.execute(
        select(
            ClientProductEnvironment.product_environment_id,
            DeploymentPackage.id,
            DeploymentPackage.description,
            DeploymentPackage.created_at,
        )
        .select_from(DeploymentRequestTarget)
        .join(ClientProductEnvironment, DeploymentRequestTarget.client_product_environment_id == ClientProductEnvironment.id)
        .join(DeploymentRequest, DeploymentRequestTarget.deployment_request_id == DeploymentRequest.id)
        .join(DeploymentPackage, DeploymentRequest.deployment_package_id == DeploymentPackage.id)
        .where(
            DeploymentRequestTarget.status == DeploymentRequestTargetStatus.Applied,
            ClientProductEnvironment.product_environment_id.in_(pe_ids),
            DeploymentPackage.custom_client_id.is_(None),
        )
        .distinct()
    ).all()

    latest: dict[uuid.UUID, LatestPackage] = {}
    for pe_id, package_id, description, created_at in applied:
        current = latest.get(pe_id)
        if current is None or created_at > current.created_at:
            latest[pe_id] = LatestPackage(package_id, description, created_at)

    # Solicitudes enviadas que todavía no se aplican en la instalación.
    waiting = db.execute(
        select(
            DeploymentRequestTarget.client_product_environment_id,
            DeploymentRequestTarget.deployment_request_id,
            DeploymentRequest.request_number,
        )
        .join(DeploymentRequest, DeploymentRequestTarget.deployment_request_id == DeploymentRequest.id)
        .where(
            DeploymentRequestTarget.client_product_environment_id.in_(installation_ids),
            DeploymentRequestTarget.status.in_(_WAITING_TARGETS),
            DeploymentRequest.status.in_(_IN_FLIGHT_REQUESTS),
        )
    ).all()

    pending: dict[uuid.UUID, PendingRequest] = {}
    for installation_id, request_id, number in waiting:
        current_pending = pending.get(installation_id)
        if current_pending is None or number > current_pending.request_number:
            pending[installation_id] = PendingRequest(request_id, number)

    return installations, latest, pending


# ---------------------------------------------------------------------------------------------- artefactos

_ARTIFACT_LOAD = (joinedload(ProductArtifact.owner_client),)


def get_product_artifact(db: Session, id: uuid.UUID) -> ProductArtifact | None:
    return db.scalars(select(ProductArtifact).where(ProductArtifact.id == id).options(*_ARTIFACT_LOAD)).first()


def find_product_artifact(
    db: Session, product_id: uuid.UUID, type: ProductArtifactType, code: str, owner_client_id: uuid.UUID | None
) -> ProductArtifact | None:
    """Versión de un artefacto para un dueño (None = versión general)."""
    normalized = ProductArtifact.normalize_code(code)
    owner_filter = (
        ProductArtifact.owner_client_id.is_(None)
        if owner_client_id is None
        else ProductArtifact.owner_client_id == owner_client_id
    )
    return db.scalars(
        select(ProductArtifact)
        .where(
            ProductArtifact.product_id == product_id,
            ProductArtifact.type == type,
            ProductArtifact.code == normalized,
            owner_filter,
        )
        .options(*_ARTIFACT_LOAD)
    ).first()


def list_product_artifacts(
    db: Session, product_id: uuid.UUID, type: ProductArtifactType | None, search: str | None
) -> list[ProductArtifact]:
    query = select(ProductArtifact).where(ProductArtifact.product_id == product_id).options(*_ARTIFACT_LOAD)
    if type is not None:
        query = query.where(ProductArtifact.type == type)
    if search and search.strip():
        pattern = _like(search.strip())
        query = query.where(
            or_(
                ProductArtifact.code.ilike(pattern, escape="\\"),
                ProductArtifact.name.ilike(pattern, escape="\\"),
                ProductArtifact.path.ilike(pattern, escape="\\"),
            )
        )
    return list(
        db.scalars(
            query.order_by(ProductArtifact.type, ProductArtifact.code, ProductArtifact.owner_client_id.is_not(None))
        )
    )


def artifact_is_used_in_packages(db: Session, id: uuid.UUID, exclude_package_id: uuid.UUID | None = None) -> bool:
    condition = [
        DeploymentPackageArtifact.product_artifact_id == id,
        DeploymentPackageArtifact.is_deleted.is_(False),
    ]
    if exclude_package_id is not None:
        condition.append(DeploymentPackageArtifact.deployment_package_id != exclude_package_id)
    return db.scalar(select(exists().where(*condition))) or False


# ----------------------------------------------------------------------------------------------- paquetes

_PACKAGE_LOAD = (
    joinedload(DeploymentPackage.product),
    joinedload(DeploymentPackage.custom_client),
    selectinload(DeploymentPackage.artifacts)
    .joinedload(DeploymentPackageArtifact.product_artifact)
    .joinedload(ProductArtifact.owner_client),
)


def get_package(db: Session, id: uuid.UUID) -> DeploymentPackage | None:
    return db.scalars(select(DeploymentPackage).where(DeploymentPackage.id == id).options(*_PACKAGE_LOAD)).first()


def list_packages(db: Session, product_id: uuid.UUID | None) -> list[DeploymentPackage]:
    query = select(DeploymentPackage).options(*_PACKAGE_LOAD)
    if product_id is not None:
        query = query.where(DeploymentPackage.product_id == product_id)
    return list(db.scalars(query.order_by(DeploymentPackage.created_at.desc())).unique())


def package_is_used_in_requests(db: Session, id: uuid.UUID) -> bool:
    return db.scalar(
        select(exists().where(DeploymentRequest.deployment_package_id == id, DeploymentRequest.is_deleted.is_(False)))
    ) or False


# --------------------------------------------------------------------------------------------- solicitudes

_REQUEST_LOAD = (
    selectinload(DeploymentRequest.tickets),
    joinedload(DeploymentRequest.deployment_package).joinedload(DeploymentPackage.product),
    joinedload(DeploymentRequest.deployment_package).joinedload(DeploymentPackage.custom_client),
    joinedload(DeploymentRequest.deployment_package)
    .selectinload(DeploymentPackage.artifacts)
    .joinedload(DeploymentPackageArtifact.product_artifact)
    .joinedload(ProductArtifact.owner_client),
    selectinload(DeploymentRequest.targets)
    .joinedload(DeploymentRequestTarget.installation)
    .joinedload(ClientProductEnvironment.client),
    selectinload(DeploymentRequest.targets)
    .joinedload(DeploymentRequestTarget.installation)
    .joinedload(ClientProductEnvironment.product_environment)
    .joinedload(ProductEnvironment.deployment_environment),
    selectinload(DeploymentRequest.targets).selectinload(DeploymentRequestTarget.history),
    selectinload(DeploymentRequest.targets).selectinload(DeploymentRequestTarget.artifact_results),
)


def get_request(db: Session, id: uuid.UUID) -> DeploymentRequest | None:
    """Agregado completo: paquete, artefactos, destinos con su instalación, historial, resultados y tickets."""
    return db.scalars(select(DeploymentRequest).where(DeploymentRequest.id == id).options(*_REQUEST_LOAD)).first()


def next_request_number(db: Session) -> int:
    """Número correlativo tomado de una SEQUENCE: no repite números con solicitudes simultáneas."""
    return int(db.scalar(select(func.nextval(REQUEST_NUMBER_SEQUENCE))))


@dataclass(frozen=True)
class RequestFilter:
    statuses: Sequence[DeploymentRequestStatus] | None = None
    product_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20
    created_by: uuid.UUID | None = None


def parse_request_number(search: str) -> int | None:
    """Acepta "DR-000012", "dr-12" o "12"."""
    digits = search[3:] if search.upper().startswith("DR-") else search
    try:
        return int(digits)
    except ValueError:
        return None


def search_requests(db: Session, filter: RequestFilter) -> tuple[list[DeploymentRequest], int]:
    query = select(DeploymentRequest)
    if filter.statuses:
        query = query.where(DeploymentRequest.status.in_(list(filter.statuses)))
    if filter.product_id is not None:
        query = query.where(
            DeploymentRequest.deployment_package.has(DeploymentPackage.product_id == filter.product_id)
        )
    if filter.created_by is not None:
        query = query.where(DeploymentRequest.created_by == filter.created_by)
    if filter.client_id is not None:
        query = query.where(
            DeploymentRequest.targets.any(
                and_(
                    DeploymentRequestTarget.is_deleted.is_(False),
                    DeploymentRequestTarget.installation.has(ClientProductEnvironment.client_id == filter.client_id),
                )
            )
        )
    if filter.search and filter.search.strip():
        term = filter.search.strip()
        pattern = _like(term)
        number = parse_request_number(term)
        conditions = [
            DeploymentRequest.comment.ilike(pattern, escape="\\"),
            DeploymentRequest.deployment_package.has(DeploymentPackage.description.ilike(pattern, escape="\\")),
            DeploymentRequest.tickets.any(Ticket.name.ilike(pattern, escape="\\")),
        ]
        if number is not None:
            conditions.insert(0, DeploymentRequest.request_number == number)
        query = query.where(or_(*conditions))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.options(
                joinedload(DeploymentRequest.deployment_package).joinedload(DeploymentPackage.product),
                joinedload(DeploymentRequest.deployment_package).joinedload(DeploymentPackage.custom_client),
                selectinload(DeploymentRequest.targets),
            )
            .order_by(DeploymentRequest.request_number.desc())
            .offset((filter.page - 1) * filter.page_size)
            .limit(filter.page_size)
        ).unique()
    )
    return items, int(total)


def get_tickets_by_names(db: Session, names: Collection[str]) -> list[Ticket]:
    lowered = [n.lower() for n in names]
    return list(db.scalars(select(Ticket).where(func.lower(Ticket.name).in_(lowered))))


# ------------------------------------------------------------------------------------- usuarios y roles

def get_role(db: Session, id: uuid.UUID) -> Role | None:
    return db.scalars(select(Role).where(Role.id == id)).first()


def get_role_by_name(db: Session, name: str) -> Role | None:
    return db.scalars(select(Role).where(func.lower(Role.name) == name.strip().lower())).first()


def list_roles(db: Session) -> list[Role]:
    return list(db.scalars(select(Role).order_by(func.lower(Role.name))))


def role_has_users(db: Session, id: uuid.UUID) -> bool:
    return db.scalar(select(exists().where(User.role_id == id, User.is_deleted.is_(False)))) or False


def get_user(db: Session, id: uuid.UUID) -> User | None:
    return db.scalars(select(User).where(User.id == id).options(joinedload(User.role))).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.email == email.strip().lower()).options(joinedload(User.role))).first()


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).options(joinedload(User.role)).order_by(func.lower(User.name))))


def get_user_names(db: Session, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Nombres por id, incluidos los usuarios eliminados (para mostrar quién hizo algo)."""
    if not ids:
        return {}
    rows = db.execute(
        select(User.id, User.name).where(User.id.in_(list(ids))).execution_options(include_deleted=True)
    ).all()
    return {row[0]: row[1] for row in rows}

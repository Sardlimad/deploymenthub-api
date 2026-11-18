"""Contratos de la API (DTOs). El JSON va en camelCase y los enums como texto, igual que el backend original."""
import uuid
from datetime import datetime
from enum import IntEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel

from app.domain.enums import (
    ArtifactChangeType,
    ArtifactExecutionStatus,
    DeploymentRequestStatus,
    DeploymentRequestTargetStatus,
    ProductArtifactType,
)


def parse_enum(enum_cls: type[IntEnum], value):
    """Acepta el nombre ("Applied", sin distinguir mayúsculas), el número o el propio enum."""
    if value is None or isinstance(value, enum_cls):
        return value
    if isinstance(value, bool):
        raise ValueError("Valor no válido.")
    if isinstance(value, int):
        return enum_cls(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return enum_cls(int(text))
        for member in enum_cls:
            if member.name.lower() == text.lower():
                return member
    names = ", ".join(m.name for m in enum_cls)
    raise ValueError(f"Valor no válido. Usa uno de: {names}.")


def _enum_type(enum_cls: type[IntEnum]):
    return Annotated[
        enum_cls,
        BeforeValidator(lambda v, c=enum_cls: parse_enum(c, v)),
        PlainSerializer(lambda e: e.name, return_type=str, when_used="always"),
    ]


ArtifactChangeTypeT = _enum_type(ArtifactChangeType)
ArtifactExecutionStatusT = _enum_type(ArtifactExecutionStatus)
RequestStatusT = _enum_type(DeploymentRequestStatus)
TargetStatusT = _enum_type(DeploymentRequestTargetStatus)
ArtifactTypeT = _enum_type(ProductArtifactType)


class Dto(BaseModel):
    """Respuestas: camelCase al serializar."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class Body(BaseModel):
    """Peticiones: acepta camelCase (o el nombre en snake_case). Los campos son opcionales y los valida
    app.validation para devolver los mismos mensajes que el backend original."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


T = TypeVar("T")


# ----------------------------------------------------------------------------------------------- respuestas

class AuthUserDto(Dto):
    id: uuid.UUID
    name: str
    email: str
    role: str  # Código del rol: ADMIN, INFRA o DEVELOPER.


class LoginResultDto(Dto):
    access_token: str
    expires_at: datetime
    user: AuthUserDto


class ClientDto(Dto):
    id: uuid.UUID
    code: str
    name: str
    is_on_premise: bool
    is_active: bool


class EnvironmentDto(Dto):
    id: uuid.UUID
    name: str
    code: str
    is_active: bool


class ProductEnvironmentDto(Dto):
    id: uuid.UUID
    product_id: uuid.UUID
    deployment_environment_id: uuid.UUID
    environment_code: str
    environment_name: str
    base_url: str
    is_active: bool


class ProductDto(Dto):
    id: uuid.UUID
    code: str
    name: str
    is_active: bool
    environments: list[uuid.UUID] = []  # Ids de los ambientes en los que existe el producto.
    product_environments: list[ProductEnvironmentDto] = []


class ProductArtifactDto(Dto):
    id: uuid.UUID
    product_id: uuid.UUID
    code: str
    name: str
    type: ArtifactTypeT
    description: str | None = None
    path: str | None = None
    is_active: bool
    introduced_in_package_id: uuid.UUID | None = None  # Paquete con el que entró al catálogo.
    created_at: datetime
    owner_client_id: uuid.UUID | None = None  # Dueño de la versión personalizada. None = general.
    owner_client_name: str | None = None
    is_custom: bool


class InstallationDto(Dto):
    id: uuid.UUID
    client_id: uuid.UUID
    client_code: str
    client_name: str
    product_environment_id: uuid.UUID
    product_id: uuid.UUID
    product_code: str
    product_name: str
    environment_id: uuid.UUID
    environment_code: str
    base_url: str
    is_active: bool
    current_package_id: uuid.UUID | None = None
    current_package_description: str | None = None
    current_package_applied_at: datetime | None = None


class InstallationStatusDto(InstallationDto):
    latest_package_id: uuid.UUID | None = None
    latest_package_description: str | None = None
    latest_package_created_at: datetime | None = None
    is_outdated: bool = False  # Hay un paquete más reciente aplicado en otra instalación del mismo producto/ambiente.
    pending_request_id: uuid.UUID | None = None  # Solicitud enviada que aún no se aplica en esta instalación.
    pending_request_number: int | None = None


class RoleDto(Dto):
    id: uuid.UUID
    name: str
    is_active: bool


class UserDto(Dto):
    id: uuid.UUID
    name: str
    email: str
    role_id: uuid.UUID
    role_name: str
    role_code: str
    is_active: bool
    has_password: bool  # False si el usuario aún no definió su contraseña.
    last_login_at: datetime | None = None


class PagedResult(Dto, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total_count: int


class PackageArtifactDto(Dto):
    id: uuid.UUID
    product_artifact_id: uuid.UUID
    code: str
    name: str
    type: ArtifactTypeT
    path: str | None = None
    change_type: ArtifactChangeTypeT
    is_new: bool  # El artefacto entró al catálogo con este paquete: la UI lo marca como «Nuevo».
    owner_client_id: uuid.UUID | None = None
    owner_client_name: str | None = None
    execution_order: int
    notes: str | None = None


class DeploymentPackageDto(Dto):
    id: uuid.UUID
    product_id: uuid.UUID
    product_code: str
    product_name: str
    description: str
    repository_id: str | None = None
    branch: str | None = None
    commit_id: str | None = None
    commit_author: str | None = None
    commit_message: str | None = None
    commit_date: datetime | None = None
    package_url: str | None = None
    is_locked: bool
    is_custom: bool  # Actualización personalizada: solo para este cliente y no cuenta como versión del producto.
    custom_client_id: uuid.UUID | None = None
    custom_client_name: str | None = None
    created_at: datetime
    new_artifacts_count: int
    artifacts: list[PackageArtifactDto] = []


class TargetArtifactResultDto(Dto):
    package_artifact_id: uuid.UUID
    status: ArtifactExecutionStatusT
    message: str | None = None
    attempt: int
    executed_at: datetime | None = None


class TargetStatusHistoryDto(Dto):
    from_status: TargetStatusT
    to_status: TargetStatusT
    comment: str | None = None
    changed_by: uuid.UUID | None = None
    changed_by_name: str | None = None
    changed_at: datetime


class DeploymentTargetDto(Dto):
    id: uuid.UUID
    installation_id: uuid.UUID
    client_id: uuid.UUID
    client_code: str
    client_name: str
    environment_code: str
    base_url: str
    status: TargetStatusT
    error_comment: str | None = None
    attempts: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_statuses: list[TargetStatusT] = []  # La UI arma los botones con esto.
    artifact_results: list[TargetArtifactResultDto] = []
    history: list[TargetStatusHistoryDto] = []


class DeploymentRequestSummaryDto(Dto):
    id: uuid.UUID
    request_number: int
    display_number: str
    status: RequestStatusT
    comment: str | None = None
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    package_id: uuid.UUID | None = None
    package_description: str | None = None
    custom_client_name: str | None = None  # Si el paquete es personalizado, el cliente al que va dirigido.
    is_custom: bool = False
    targets_total: int = 0
    targets_applied: int = 0
    targets_failed: int = 0
    targets_pending: int = 0
    created_at: datetime
    created_by_id: uuid.UUID | None = None
    created_by_name: str | None = None
    submitted_at: datetime | None = None
    submitted_by_id: uuid.UUID | None = None
    submitted_by_name: str | None = None
    completed_at: datetime | None = None


class DeploymentRequestDetailDto(DeploymentRequestSummaryDto):
    tickets: list[str] = []
    approved_at: datetime | None = None
    approved_by_id: uuid.UUID | None = None
    approved_by_name: str | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    package: DeploymentPackageDto | None = None
    targets: list[DeploymentTargetDto] = []


# ------------------------------------------------------------------------------------------------ peticiones

class LoginBody(Body):
    email: str | None = None
    password: str | None = None


class ChangePasswordBody(Body):
    current_password: str | None = None
    new_password: str | None = None


class RequestRecoveryBody(Body):
    email: str | None = None


class VerifyRecoveryBody(Body):
    email: str | None = None
    code: str | None = None


class ResetPasswordBody(Body):
    email: str | None = None
    code: str | None = None
    password: str | None = None


class ClientBody(Body):
    code: str | None = None
    name: str | None = None
    is_on_premise: bool = False
    is_active: bool = True


class EnvironmentBody(Body):
    code: str | None = None
    name: str | None = None
    is_active: bool = True


class ProductBody(Body):
    code: str | None = None
    name: str | None = None
    is_active: bool = True


class ProductEnvironmentBody(Body):
    product_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    base_url: str | None = None
    is_active: bool = True


class ProductArtifactBody(Body):
    product_id: uuid.UUID | None = None
    code: str | None = None
    name: str | None = None
    type: ArtifactTypeT | None = None
    description: str | None = None
    path: str | None = None
    owner_client_id: uuid.UUID | None = None
    is_active: bool = True


class InstallationBody(Body):
    client_id: uuid.UUID | None = None
    product_environment_id: uuid.UUID | None = None
    base_url: str | None = None
    is_active: bool = True


class RoleBody(Body):
    name: str | None = None


class UserBody(Body):
    name: str | None = None
    email: str | None = None
    role_id: uuid.UUID | None = None
    password: str | None = None
    is_active: bool = True


class PackageArtifactInput(Body):
    """Artefacto a incluir en un paquete. Se indica un artefacto del catálogo (productArtifactId)
    o se describe por tipo + código; en ese caso, si no existe en el catálogo, entra como nuevo."""

    product_artifact_id: uuid.UUID | None = None
    type: ArtifactTypeT | None = None
    code: str | None = None
    name: str | None = None
    path: str | None = None
    description: str | None = None
    change_type: ArtifactChangeTypeT | None = None
    execution_order: int | None = None
    notes: str | None = None


class DeploymentPackageBody(Body):
    product_id: uuid.UUID | None = None
    description: str | None = None
    repository_id: str | None = None
    branch: str | None = None
    commit_id: str | None = None
    commit_author: str | None = None
    commit_message: str | None = None
    commit_date: datetime | None = None
    package_url: str | None = None
    artifacts: list[PackageArtifactInput] | None = None
    custom_client_id: uuid.UUID | None = None


class UpdatePackageArtifactBody(Body):
    execution_order: int | None = None
    notes: str | None = None


class DeploymentRequestBody(Body):
    package_id: uuid.UUID | None = None
    comment: str | None = None
    tickets: list[str] | None = None


class CancelRequestBody(Body):
    reason: str | None = None


class AddTargetsBody(Body):
    installation_ids: list[uuid.UUID] | None = None


class ArtifactResultBody(Body):
    package_artifact_id: uuid.UUID | None = None
    status: ArtifactExecutionStatusT | None = None
    message: str | None = None


class ChangeStatusBody(Body):
    status: TargetStatusT | None = None
    comment: str | None = None
    artifact_results: list[ArtifactResultBody] | None = None

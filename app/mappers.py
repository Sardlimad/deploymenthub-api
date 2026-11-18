"""Mapeo explícito entidad → DTO (las entidades exponen colecciones y propiedades calculadas)."""
import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app import repositories as repo
from app.domain import roles as role_names
from app.domain import status as status_rules
from app.domain.enums import DeploymentRequestStatus as R
from app.domain.enums import DeploymentRequestTargetStatus as T
from app.models import (
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
    User,
)
from app.models.base import EMPTY_GUID
from app.schemas import (
    AuthUserDto,
    ClientDto,
    DeploymentPackageDto,
    DeploymentRequestDetailDto,
    DeploymentRequestSummaryDto,
    DeploymentTargetDto,
    EnvironmentDto,
    InstallationDto,
    InstallationStatusDto,
    PackageArtifactDto,
    ProductArtifactDto,
    ProductDto,
    ProductEnvironmentDto,
    RoleDto,
    TargetArtifactResultDto,
    TargetStatusHistoryDto,
    UserDto,
)


def client_dto(c: Client) -> ClientDto:
    return ClientDto(id=c.id, code=c.code, name=c.name, is_on_premise=c.is_on_premise, is_active=c.is_active)


def environment_dto(e: DeploymentEnvironment) -> EnvironmentDto:
    return EnvironmentDto(id=e.id, code=e.code, name=e.name, is_active=e.is_active)


def product_environment_dto(pe: ProductEnvironment) -> ProductEnvironmentDto:
    env = pe.deployment_environment
    return ProductEnvironmentDto(
        id=pe.id,
        product_id=pe.product_id,
        deployment_environment_id=pe.deployment_environment_id,
        environment_code=env.code if env else "",
        environment_name=env.name if env else "",
        base_url=pe.base_url or "",
        is_active=pe.is_active,
    )


def product_dto(p: Product) -> ProductDto:
    return ProductDto(
        id=p.id,
        code=p.code,
        name=p.name,
        is_active=p.is_active,
        environments=[pe.deployment_environment_id for pe in p.product_environments],
        product_environments=[product_environment_dto(pe) for pe in p.product_environments],
    )


def product_artifact_dto(a: ProductArtifact) -> ProductArtifactDto:
    return ProductArtifactDto(
        id=a.id,
        product_id=a.product_id,
        code=a.code,
        name=a.name,
        type=a.type,
        description=a.description,
        path=a.path,
        is_active=a.is_active,
        introduced_in_package_id=a.introduced_in_package_id,
        created_at=a.created_at,
        owner_client_id=a.owner_client_id,
        owner_client_name=a.owner_client.name if a.owner_client else None,
        is_custom=a.owner_client_id is not None,
    )


def installation_dto(i: ClientProductEnvironment) -> InstallationDto:
    return InstallationDto(**_installation_fields(i))


def _installation_fields(i: ClientProductEnvironment) -> dict:
    pe = i.product_environment
    return dict(
        id=i.id,
        client_id=i.client_id,
        client_code=i.client.code,
        client_name=i.client.name,
        product_environment_id=i.product_environment_id,
        product_id=pe.product_id,
        product_code=pe.product.code,
        product_name=pe.product.name,
        environment_id=pe.deployment_environment_id,
        environment_code=pe.deployment_environment.code,
        base_url=i.base_url or "",
        is_active=i.is_active,
        current_package_id=i.current_package_id,
        current_package_description=i.current_package.description if i.current_package else None,
        current_package_applied_at=i.current_package_applied_at,
    )


def installation_status_dtos(db: Session, filter: repo.InstallationFilter) -> list[InstallationStatusDto]:
    installations, latest_by_pe, pending_by_installation = repo.installation_status_data(db, filter)
    result: list[InstallationStatusDto] = []
    for installation in installations:
        dto = InstallationStatusDto(**_installation_fields(installation))
        latest = latest_by_pe.get(installation.product_environment_id)
        if latest is not None:
            dto.latest_package_id = latest.package_id
            dto.latest_package_description = latest.description
            dto.latest_package_created_at = latest.created_at
            dto.is_outdated = installation.current_package_id != latest.package_id and (
                installation.current_package is None or installation.current_package.created_at < latest.created_at
            )
        waiting = pending_by_installation.get(installation.id)
        if waiting is not None:
            dto.pending_request_id = waiting.request_id
            dto.pending_request_number = waiting.request_number
        result.append(dto)
    return [r for r in result if r.is_outdated] if filter.only_outdated else result


def role_dto(r: Role) -> RoleDto:
    return RoleDto(id=r.id, name=r.name, is_active=r.is_active)


def user_dto(u: User) -> UserDto:
    return UserDto(
        id=u.id,
        name=u.name,
        email=u.email,
        role_id=u.role_id,
        role_name=u.role.name if u.role else "",
        role_code=role_names.normalize(u.role.name) if u.role else "",
        is_active=u.is_active,
        has_password=u.password_hash is not None,
        last_login_at=u.last_login_at,
    )


def auth_user_dto(u: User) -> AuthUserDto:
    return AuthUserDto(id=u.id, name=u.name, email=u.email, role=role_names.normalize(u.role.name))


def package_artifact_dto(pa: DeploymentPackageArtifact) -> PackageArtifactDto:
    art = pa.product_artifact
    return PackageArtifactDto(
        id=pa.id,
        product_artifact_id=pa.product_artifact_id,
        code=art.code,
        name=art.name,
        type=art.type,
        path=art.path,
        change_type=pa.change_type,
        is_new=pa.is_new,
        owner_client_id=art.owner_client_id,
        owner_client_name=art.owner_client.name if art.owner_client else None,
        execution_order=pa.execution_order,
        notes=pa.notes,
    )


def package_dto(p: DeploymentPackage) -> DeploymentPackageDto:
    return DeploymentPackageDto(
        id=p.id,
        product_id=p.product_id,
        product_code=p.product.code if p.product else "",
        product_name=p.product.name if p.product else "",
        description=p.description,
        repository_id=p.repository_id,
        branch=p.branch,
        commit_id=p.commit_id,
        commit_author=p.commit_author,
        commit_message=p.commit_message,
        commit_date=p.commit_date,
        package_url=p.package_url,
        is_locked=p.is_locked,
        is_custom=p.is_custom,
        custom_client_id=p.custom_client_id,
        custom_client_name=p.custom_client.name if p.custom_client else None,
        created_at=p.created_at,
        new_artifacts_count=sum(1 for a in p.artifacts if a.is_new),
        artifacts=[package_artifact_dto(a) for a in sorted(p.artifacts, key=lambda a: a.execution_order)],
    )


def target_dto(t: DeploymentRequestTarget) -> DeploymentTargetDto:
    inst = t.installation
    request_status = t.deployment_request.status if t.deployment_request is not None else None
    next_statuses = [] if request_status in (R.Draft, R.Cancelled) else list(status_rules.next_statuses(t.status))
    return DeploymentTargetDto(
        id=t.id,
        installation_id=t.client_product_environment_id,
        client_id=inst.client_id,
        client_code=inst.client.code,
        client_name=inst.client.name,
        environment_code=inst.product_environment.deployment_environment.code,
        base_url=inst.base_url or "",
        status=t.status,
        error_comment=t.error_comment,
        attempts=t.attempts,
        started_at=t.started_at,
        finished_at=t.finished_at,
        next_statuses=next_statuses,
        artifact_results=[
            TargetArtifactResultDto(
                package_artifact_id=r.deployment_package_artifact_id,
                status=r.status,
                message=r.message,
                attempt=r.attempt,
                executed_at=r.executed_at,
            )
            for r in t.artifact_results
        ],
        history=[
            TargetStatusHistoryDto(
                from_status=h.from_status,
                to_status=h.to_status,
                comment=h.comment,
                changed_by=h.changed_by,
                changed_at=h.changed_at,
            )
            for h in sorted(t.history, key=lambda h: h.changed_at, reverse=True)
        ],
    )


def _fill_summary(dto: DeploymentRequestSummaryDto, r: DeploymentRequest) -> None:
    pkg = r.deployment_package
    dto.id = r.id
    dto.request_number = r.request_number
    dto.display_number = r.display_number
    dto.status = r.status
    dto.comment = r.comment
    dto.product_id = pkg.product_id if pkg else None
    dto.product_name = pkg.product.name if pkg and pkg.product else None
    dto.package_id = r.deployment_package_id
    dto.package_description = pkg.description if pkg else None
    dto.custom_client_name = pkg.custom_client.name if pkg and pkg.custom_client else None
    dto.is_custom = dto.custom_client_name is not None
    # EMPTY_GUID = creada sin usuario.
    dto.created_by_id = None if r.created_by == EMPTY_GUID else r.created_by
    dto.submitted_by_id = r.submitted_by
    dto.targets_total = len(r.targets)
    dto.targets_applied = sum(1 for t in r.targets if t.status == T.Applied)
    dto.targets_failed = sum(1 for t in r.targets if t.status in (T.Failed, T.RolledBack))
    dto.targets_pending = sum(1 for t in r.targets if t.status in (T.Pending, T.Scheduled, T.InProgress))
    dto.created_at = r.created_at
    dto.submitted_at = r.submitted_at
    dto.completed_at = r.completed_at


def request_summary_dto(r: DeploymentRequest, names: dict[uuid.UUID, str] | None = None) -> DeploymentRequestSummaryDto:
    dto = DeploymentRequestSummaryDto(
        id=r.id, request_number=r.request_number, display_number=r.display_number, status=r.status, created_at=r.created_at
    )
    _fill_summary(dto, r)
    if names is not None:
        dto.created_by_name = names.get(dto.created_by_id) if dto.created_by_id else None
        dto.submitted_by_name = names.get(r.submitted_by) if r.submitted_by else None
    return dto


def request_detail_dto(r: DeploymentRequest, db: Session | None = None) -> DeploymentRequestDetailDto:
    """Detalle con los nombres de quién creó, envió, aprobó y cambió cada estado (si se pasa la sesión)."""
    dto = DeploymentRequestDetailDto(
        id=r.id, request_number=r.request_number, display_number=r.display_number, status=r.status, created_at=r.created_at
    )
    _fill_summary(dto, r)
    dto.tickets = sorted(t.name for t in r.tickets)
    dto.approved_at = r.approved_at
    dto.approved_by_id = r.approved_by
    dto.cancelled_at = r.cancelled_at
    dto.cancellation_reason = r.cancellation_reason
    dto.package = package_dto(r.deployment_package) if r.deployment_package else None
    dto.targets = [
        target_dto(t) for t in sorted(r.targets, key=lambda t: t.installation.client.name.lower())
    ]

    if db is not None:
        history = [h for t in dto.targets for h in t.history]
        ids: Iterable[uuid.UUID | None] = [
            dto.created_by_id, dto.submitted_by_id, dto.approved_by_id, *(h.changed_by for h in history)
        ]
        names = repo.get_user_names(db, {i for i in ids if i is not None})

        def name_of(id: uuid.UUID | None) -> str | None:
            return names.get(id) if id is not None else None

        dto.created_by_name = name_of(dto.created_by_id)
        dto.submitted_by_name = name_of(dto.submitted_by_id)
        dto.approved_by_name = name_of(dto.approved_by_id)
        for entry in history:
            entry.changed_by_name = name_of(entry.changed_by)
    return dto

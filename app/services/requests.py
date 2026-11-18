"""Casos de uso de solicitudes de despliegue y de sus clientes destino.

Cada caso de uso guarda primero (commit) y DESPUÉS avisa (tiempo real y correo): no se avisa de cambios
que se revirtieron, y un fallo al avisar nunca deshace el cambio.
"""
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import mappers
from app import repositories as repo
from app.domain.enums import DeploymentRequestStatus, DeploymentRequestTargetStatus
from app.domain.exceptions import NotFoundException
from app.models import ArtifactResultInput, DeploymentRequest, DeploymentRequestTarget, Ticket
from app.models.base import EMPTY_GUID
from app.notifications.composer import ChangeKind, DeploymentChange
from app.realtime import EventTypes, RealtimeEvent, hub
from app.schemas import (
    AddTargetsBody,
    ChangeStatusBody,
    DeploymentRequestBody,
    DeploymentRequestDetailDto,
    DeploymentRequestSummaryDto,
    DeploymentTargetDto,
    PagedResult,
)
from app.state import get_notification_queue
from app.validation import Validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------------------------- eventos en tiempo real

def _request_event(type_: str, request: DeploymentRequest) -> RealtimeEvent:
    return RealtimeEvent(type_, request.id, mappers.request_summary_dto(request))


def _target_event(request: DeploymentRequest, target: DeploymentRequestTarget) -> RealtimeEvent:
    return RealtimeEvent(
        EventTypes.TARGET_STATUS_CHANGED,
        request.id,
        {
            "requestId": request.id,
            "displayNumber": request.display_number,
            "requestStatus": request.status,
            "target": mappers.target_dto(target),
        },
    )


def _installation_event(target: DeploymentRequestTarget) -> RealtimeEvent:
    inst = target.installation
    return RealtimeEvent(
        EventTypes.INSTALLATION_UPDATED,
        None,
        {
            "installationId": target.client_product_environment_id,
            "clientId": inst.client_id,
            "currentPackageId": inst.current_package_id,
            "currentPackageAppliedAt": inst.current_package_applied_at,
        },
    )


def _notify(kind: ChangeKind, request: DeploymentRequest, user_id: uuid.UUID | None, **extra) -> None:
    get_notification_queue().enqueue(DeploymentChange(kind, request.id, user_id, _now(), **extra))


# ------------------------------------------------------------------------------------------------- tickets

def _resolve_tickets(db: Session, names: Sequence[str] | None) -> list[Ticket]:
    """Devuelve los tickets con esos nombres, creando los que no existan."""
    clean: list[str] = []
    seen: set[str] = set()
    for n in names or []:
        if n and n.strip() and n.strip().lower() not in seen:
            seen.add(n.strip().lower())
            clean.append(n.strip())
    if not clean:
        return []

    existing = repo.get_tickets_by_names(db, clean)
    by_name = {t.name.lower(): t for t in existing}
    tickets = list(existing)
    for name in clean:
        if name.lower() not in by_name:
            ticket = Ticket(name)
            db.add(ticket)
            tickets.append(ticket)
    return tickets


def _load(db: Session, id: uuid.UUID, message: str) -> DeploymentRequest:
    request = repo.get_request(db, id)
    if request is None:
        raise NotFoundException(message)
    return request


# ------------------------------------------------------------------------------------------------ consultas

def search_requests(
    db: Session,
    user_id: uuid.UUID | None,
    statuses: Sequence[DeploymentRequestStatus] | None,
    product_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    search: str | None,
    page: int,
    page_size: int,
    only_mine: bool,
) -> PagedResult[DeploymentRequestSummaryDto]:
    v = Validator()
    v.greater_than("Page", page, 0)
    v.between("PageSize", page_size, 1, 100)
    v.max_len("Search", search, 100)
    v.raise_if_invalid()

    filter = repo.RequestFilter(
        statuses=statuses,
        product_id=product_id,
        client_id=client_id,
        search=search,
        page=page,
        page_size=page_size,
        # Sin sesión no hay «mías»: EMPTY_GUID no coincide con ninguna solicitud con autor.
        created_by=(user_id or EMPTY_GUID) if only_mine else None,
    )
    requests, total = repo.search_requests(db, filter)

    ids = {r.created_by for r in requests if r.created_by != EMPTY_GUID} | {
        r.submitted_by for r in requests if r.submitted_by is not None
    }
    names = repo.get_user_names(db, ids)
    return PagedResult[DeploymentRequestSummaryDto](
        items=[mappers.request_summary_dto(r, names) for r in requests],
        page=page,
        page_size=page_size,
        total_count=total,
    )


def get_request(db: Session, id: uuid.UUID) -> DeploymentRequestDetailDto:
    request = _load(db, id, "Solicitud de despliegue no encontrada.")
    return mappers.request_detail_dto(request, db)


def get_target(db: Session, request_id: uuid.UUID, target_id: uuid.UUID) -> DeploymentTargetDto:
    request = _load(db, request_id, "Solicitud de despliegue no encontrada.")
    target = next((t for t in request.targets if t.id == target_id), None)
    if target is None:
        raise NotFoundException("El cliente destino no pertenece a esta solicitud.")
    return mappers.target_dto(target)


# ------------------------------------------------------------------------------------------------ comandos

def _validate_request_body(body: DeploymentRequestBody | None) -> None:
    v = Validator()
    if body is not None:
        v.max_len("Comment", body.comment, 1000)
        v.for_each_max_len("Tickets", body.tickets, 150)
    v.raise_if_invalid()


def create_request(db: Session, body: DeploymentRequestBody | None) -> DeploymentRequestDetailDto:
    """Crea una solicitud en borrador. El paquete, comentario y tickets son opcionales en este paso."""
    body = body or DeploymentRequestBody()
    _validate_request_body(body)

    number = repo.next_request_number(db)
    request = DeploymentRequest.create(number)
    request.update(body.comment, _resolve_tickets(db, body.tickets))

    if body.package_id is not None:
        package = repo.get_package(db, body.package_id)
        if package is None:
            raise NotFoundException("No existe el paquete de despliegue.")
        request.associate_package(package)

    db.add(request)
    db.commit()

    hub.publish(_request_event(EventTypes.DEPLOYMENT_CREATED, request))
    saved = repo.get_request(db, request.id)
    return mappers.request_detail_dto(saved, db)


def update_request(db: Session, id: uuid.UUID, body: DeploymentRequestBody) -> None:
    _validate_request_body(body)
    request = _load(db, id, "No existe la solicitud de despliegue.")
    request.update(body.comment, _resolve_tickets(db, body.tickets))
    db.commit()
    hub.publish(_request_event(EventTypes.DEPLOYMENT_UPDATED, request))


def associate_package(db: Session, request_id: uuid.UUID, package_id: uuid.UUID) -> None:
    request = _load(db, request_id, "No existe la solicitud de despliegue.")
    package = repo.get_package(db, package_id)
    if package is None:
        raise NotFoundException("No existe el paquete de despliegue.")
    request.associate_package(package)
    db.commit()
    hub.publish(_request_event(EventTypes.DEPLOYMENT_UPDATED, request))


def submit_request(db: Session, request_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """Envía la solicitud: queda pendiente de aplicar en cada cliente y el paquete se bloquea."""
    request = _load(db, request_id, "La solicitud no existe.")
    request.submit(user_id, _now())
    db.commit()
    _notify(ChangeKind.Submitted, request, user_id)
    hub.publish(_request_event(EventTypes.DEPLOYMENT_SUBMITTED, request))


def approve_request(db: Session, request_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    request = _load(db, request_id, "La solicitud no existe.")
    request.approve(user_id, _now())
    db.commit()
    _notify(ChangeKind.Approved, request, user_id)
    hub.publish(_request_event(EventTypes.DEPLOYMENT_STATUS_CHANGED, request))


def cancel_request(db: Session, request_id: uuid.UUID, reason: str | None, user_id: uuid.UUID | None) -> None:
    """Cancela los clientes que aún no se desplegaron. Si alguno ya terminó, el estado general refleja lo que sí se hizo."""
    v = Validator()
    v.max_len("Reason", reason, 1000)
    v.raise_if_invalid()

    request = _load(db, request_id, "La solicitud no existe.")
    # Descartar un borrador no avisa a nadie: Infraestructura nunca lo vio.
    was_draft = request.status == DeploymentRequestStatus.Draft
    request.cancel(reason, user_id, _now())
    db.commit()
    if not was_draft:
        _notify(ChangeKind.Cancelled, request, user_id)
    hub.publish(_request_event(EventTypes.DEPLOYMENT_STATUS_CHANGED, request))


# ------------------------------------------------------------------------------------------- destinos

def add_targets(db: Session, request_id: uuid.UUID, body: AddTargetsBody) -> list[DeploymentTargetDto]:
    """Agrega clientes destino a una solicitud en borrador. Cada destino es una instalación
    (cliente × producto × ambiente), no un ambiente de producto."""
    v = Validator()
    v.not_empty("InstallationIds", body.installation_ids, "Elige al menos un cliente.")
    v.raise_if_invalid()

    request = _load(db, request_id, "No existe la solicitud de despliegue.")
    ids = list(dict.fromkeys(body.installation_ids))
    installations = repo.get_installations(db, ids)
    missing = set(ids) - {i.id for i in installations}
    if missing:
        raise NotFoundException(f"No existen {len(missing)} de las instalaciones elegidas.")

    targets = [request.add_target(i) for i in installations]
    db.commit()
    hub.publish(_request_event(EventTypes.DEPLOYMENT_UPDATED, request))
    return [mappers.target_dto(t) for t in targets]


def remove_target(db: Session, request_id: uuid.UUID, target_id: uuid.UUID) -> None:
    request = _load(db, request_id, "No existe la solicitud de despliegue.")
    request.remove_target(target_id)
    db.commit()
    hub.publish(_request_event(EventTypes.DEPLOYMENT_UPDATED, request))


def change_target_status(
    db: Session, request_id: uuid.UUID, target_id: uuid.UUID, body: ChangeStatusBody, user_id: uuid.UUID | None
) -> DeploymentRequestDetailDto:
    """Reporta el estado de un cliente destino (en curso, aplicado, fallido, revertido, reintento...).
    Opcionalmente detalla el resultado de cada artefacto del paquete en ese cliente."""
    v = Validator()
    v.not_empty("DeploymentRequestId", request_id)
    v.not_empty("TargetId", target_id)
    v.not_null("Status", body.status)
    v.max_len("Comment", body.comment, 2000)
    if body.status == DeploymentRequestTargetStatus.Failed:
        v.not_empty("Comment", body.comment, "Indica el motivo del fallo.")
    for i, r in enumerate(body.artifact_results or []):
        v.not_empty(f"ArtifactResults[{i}].PackageArtifactId", r.package_artifact_id)
        v.not_null(f"ArtifactResults[{i}].Status", r.status)
        v.max_len(f"ArtifactResults[{i}].Message", r.message, 4000)
    v.raise_if_invalid()

    request = _load(db, request_id, "No existe la solicitud de despliegue.")
    previous_request_status = request.status
    previous_target_status = request.get_target(target_id).status

    results = [ArtifactResultInput(r.package_artifact_id, r.status, r.message) for r in body.artifact_results or []]
    target = request.change_target_status(target_id, body.status, body.comment, results, user_id, _now())
    db.commit()

    _notify(
        ChangeKind.TargetStatusChanged,
        request,
        user_id,
        target_id=target.id,
        from_status=previous_target_status,
        to_status=target.status,
        comment=body.comment,
    )
    hub.publish(_target_event(request, target))
    if request.status != previous_request_status:
        hub.publish(_request_event(EventTypes.DEPLOYMENT_STATUS_CHANGED, request))
    if body.status in (DeploymentRequestTargetStatus.Applied, DeploymentRequestTargetStatus.RolledBack):
        hub.publish(_installation_event(target))

    return mappers.request_detail_dto(request, db)

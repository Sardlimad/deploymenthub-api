"""A quién avisar y qué decirle. Sin E/S: se prueba con datos en memoria.

Destinatarios: Infraestructura y Administración (activos), más quien creó y quien envió la solicitud.
Nunca quien hizo el cambio: ya lo sabe.
"""
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain import roles as role_names
from app.domain.enums import DeploymentRequestStatus as R
from app.domain.enums import DeploymentRequestTargetStatus as T
from app.notifications import templates


class ChangeKind(str, Enum):
    Submitted = "Submitted"
    Approved = "Approved"
    Cancelled = "Cancelled"
    TargetStatusChanged = "TargetStatusChanged"


@dataclass(frozen=True)
class DeploymentChange:
    """Un cambio que merece aviso por correo. Se registra DESPUÉS de guardar, igual que el tiempo real."""

    kind: ChangeKind
    request_id: uuid.UUID
    actor_id: uuid.UUID | None
    occurred_at: datetime
    target_id: uuid.UUID | None = None
    from_status: T | None = None
    to_status: T | None = None
    comment: str | None = None


@dataclass(frozen=True)
class NotifiedRequest:
    """Lo que el redactor necesita de la solicitud, sin depender del ORM."""

    id: uuid.UUID
    display_number: str
    product_name: str | None
    package_description: str | None
    status: R
    created_by_id: uuid.UUID | None
    submitted_by_id: uuid.UUID | None
    targets_total: int
    target_names: Mapping[uuid.UUID, str]
    cancellation_reason: str | None


@dataclass(frozen=True)
class NotifiedUser:
    id: uuid.UUID
    name: str
    email: str
    role_code: str
    is_active: bool


@dataclass(frozen=True)
class DeploymentEmail:
    to: NotifiedUser
    subject: str
    body: str
    html: str | None = None


def recipients(
    request: NotifiedRequest, users: Iterable[NotifiedUser], actor_ids: Iterable[uuid.UUID | None]
) -> list[NotifiedUser]:
    actors = {a for a in actor_ids if a is not None}
    candidates = [
        u
        for u in users
        if u.is_active
        and u.email.strip()
        and u.id not in actors
        and (
            u.role_code in (role_names.INFRA, role_names.ADMIN)
            or u.id == request.created_by_id
            or u.id == request.submitted_by_id
        )
    ]
    unique: dict[str, NotifiedUser] = {}
    for u in candidates:  # un correo por dirección
        unique.setdefault(u.email.strip().lower(), u)
    return sorted(unique.values(), key=lambda u: u.name.casefold())


def compose(
    request: NotifiedRequest,
    changes: Sequence[DeploymentChange],
    users: Sequence[NotifiedUser],
    public_url: str | None,
) -> list[DeploymentEmail]:
    """Un correo por destinatario con TODOS los cambios agrupados de esa solicitud."""
    if not changes:
        return []

    names = {u.id: u.name for u in users}

    def who(id: uuid.UUID | None) -> str:
        return names.get(id, "Alguien") if id is not None else "Alguien"

    subject = f"[DeploymentHub] {request.display_number} · {_title(request, changes)}"
    ordered = sorted(changes, key=lambda c: c.occurred_at)
    items = [_item(request, c, who(c.actor_id)) for c in ordered]
    lines = [_format_line(i) for i in items]
    link = f"{public_url.rstrip('/')}/deployments/{request.id}" if public_url and public_url.strip() else None
    recipient_list = recipients(request, users, [c.actor_id for c in changes])
    return [
        DeploymentEmail(u, subject, _body(request, lines, link, u), _html(request, items, link, u))
        for u in recipient_list
    ]


def _title(request: NotifiedRequest, changes: Sequence[DeploymentChange]) -> str:
    if len(changes) == 1:
        c = changes[0]
        if c.kind == ChangeKind.Submitted:
            return "enviada, pendiente de aplicar"
        if c.kind == ChangeKind.Approved:
            return "aprobada"
        if c.kind == ChangeKind.Cancelled:
            return "cancelada"
        return f"{_client(request, c.target_id)}: {target_label(c.to_status)}"
    return f"{len(changes)} cambios · {request_label(request.status).lower()}"


def _item(request: NotifiedRequest, c: DeploymentChange, actor: str) -> templates.Change:
    comment = None
    if c.kind == ChangeKind.Submitted:
        noun = "cliente" if request.targets_total == 1 else "clientes"
        text, tone = f"{actor} la envió a {request.targets_total} {noun}. Queda pendiente de aplicar.", "warning"
    elif c.kind == ChangeKind.Approved:
        text, tone = f"{actor} la aprobó.", "success"
    elif c.kind == ChangeKind.Cancelled:
        reason = request.cancellation_reason
        text = f"{actor} la canceló" + ("." if not (reason or "").strip() else f": «{reason}».")
        tone = "danger"
    else:
        text = f"{_client(request, c.target_id)}: {target_label(c.from_status)} → {target_label(c.to_status)} (por {actor})."
        tone = _TARGET_TONES.get(c.to_status, "info")
        if (c.comment or "").strip():
            comment = c.comment.strip()
    return templates.Change(text, tone, comment)


def _format_line(item: templates.Change) -> str:
    text = f"• {item.text}"
    return text + (f"\n    Comentario: {item.comment}" if item.comment else "")


def _html(request: NotifiedRequest, items: Sequence[templates.Change], link: str | None, to: NotifiedUser) -> str:
    return templates.deployment_email(
        to.name,
        request.display_number,
        (request.package_description or "").strip() or None,
        (request.product_name or "").strip() or None,
        request_label(request.status),
        _REQUEST_TONES.get(request.status, "neutral"),
        items,
        link,
        _reason(request, to),
    )


def _body(request: NotifiedRequest, lines: Sequence[str], link: str | None, to: NotifiedUser) -> str:
    out: list[str] = [f"Hola, {to.name}:", ""]
    what = f" «{request.package_description}»" if (request.package_description or "").strip() else ""
    product = f" de {request.product_name}" if (request.product_name or "").strip() else ""
    out.append(f"Hubo cambios en la solicitud {request.display_number}{what}{product}:")
    out.append("")
    out.extend(lines)
    out.append("")
    out.append(f"Estado general: {request_label(request.status)}.")
    if link is not None:
        out.extend(["", f"Ver la solicitud: {link}"])
    out.extend(
        [
            "",
            "—",
            f"Recibes este aviso porque {_reason(request, to)}. Es un mensaje automático de DeploymentHub.",
        ]
    )
    return "\n".join(out) + "\n"


def _reason(request: NotifiedRequest, u: NotifiedUser) -> str:
    if u.id == request.created_by_id:
        return "creaste esta solicitud"
    if u.id == request.submitted_by_id:
        return "enviaste esta solicitud"
    return "eres de Infraestructura" if u.role_code == role_names.INFRA else "eres administrador"


def _client(request: NotifiedRequest, target_id: uuid.UUID | None) -> str:
    return request.target_names.get(target_id, "Un cliente") if target_id is not None else "Un cliente"


_REQUEST_LABELS = {
    R.Draft: "Borrador",
    R.Pending: "Pendiente",
    R.Approved: "Aprobada",
    R.InProgress: "En curso",
    R.Completed: "Completada",
    R.PartiallyCompleted: "Completada en parte",
    R.Failed: "Con fallos",
    R.Cancelled: "Cancelada",
}

_TARGET_LABELS = {
    T.Pending: "Pendiente",
    T.Scheduled: "Programado",
    T.InProgress: "Aplicando",
    T.Applied: "Aplicado",
    T.Failed: "Con fallo",
    T.Cancelled: "Cancelado",
    T.Skipped: "Omitido",
    T.RolledBack: "Revertido",
}


_REQUEST_TONES = {
    R.Draft: "neutral",
    R.Pending: "warning",
    R.Approved: "info",
    R.InProgress: "info",
    R.Completed: "success",
    R.PartiallyCompleted: "warning",
    R.Failed: "danger",
    R.Cancelled: "danger",
}

_TARGET_TONES = {
    T.Pending: "warning",
    T.Scheduled: "info",
    T.InProgress: "info",
    T.Applied: "success",
    T.Failed: "danger",
    T.Cancelled: "danger",
    T.Skipped: "neutral",
    T.RolledBack: "warning",
}


def request_label(status: R) -> str:
    return _REQUEST_LABELS.get(status, status.name)


def target_label(status: T | None) -> str:
    return "—" if status is None else _TARGET_LABELS.get(status, status.name)

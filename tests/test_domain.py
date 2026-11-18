"""Reglas puras de estados y redacción de avisos (sin base de datos)."""
import uuid
from datetime import datetime, timezone

from app.domain import roles
from app.domain.enums import DeploymentRequestStatus as R
from app.domain.enums import DeploymentRequestTargetStatus as T
from app.domain.status import calculate_request_status, can_transition, next_statuses
from app.notifications import composer
from app.notifications.composer import ChangeKind, DeploymentChange, NotifiedRequest, NotifiedUser


def test_borrador_y_cancelada_no_cambian_con_los_destinos():
    assert calculate_request_status(R.Draft, [T.Applied]) == R.Draft
    assert calculate_request_status(R.Cancelled, [T.Applied]) == R.Cancelled


def test_todos_aplicados_es_completada():
    assert calculate_request_status(R.Pending, [T.Applied, T.Applied]) == R.Completed


def test_mezcla_de_aplicados_y_fallidos_es_parcial():
    assert calculate_request_status(R.InProgress, [T.Applied, T.Failed]) == R.PartiallyCompleted


def test_todos_fallidos_es_fallida():
    assert calculate_request_status(R.InProgress, [T.Failed, T.RolledBack]) == R.Failed


def test_uno_en_curso_es_en_curso():
    assert calculate_request_status(R.Pending, [T.InProgress, T.Pending]) == R.InProgress
    assert calculate_request_status(R.Pending, [T.Applied, T.Pending]) == R.InProgress


def test_todo_pendiente_conserva_la_aprobacion():
    assert calculate_request_status(R.Approved, [T.Pending, T.Scheduled]) == R.Approved
    assert calculate_request_status(R.Pending, [T.Pending]) == R.Pending


def test_cancelados_y_omitidos_no_cuentan():
    assert calculate_request_status(R.Pending, [T.Cancelled, T.Applied]) == R.Completed
    assert calculate_request_status(R.Pending, [T.Cancelled, T.Cancelled]) == R.Cancelled
    assert calculate_request_status(R.Pending, [T.Skipped]) == R.Completed


def test_transiciones_de_destino():
    assert can_transition(T.Pending, T.Applied)
    assert can_transition(T.Applied, T.RolledBack)
    assert not can_transition(T.Applied, T.Failed)
    assert not can_transition(T.Cancelled, T.Pending)
    assert list(next_statuses(T.InProgress)) == [T.Applied, T.Failed]
    assert list(next_statuses(T.Skipped)) == []


def test_roles_en_espanol_equivalen_a_los_codigos():
    assert roles.normalize("Administrador") == roles.ADMIN
    assert roles.normalize(" infraestructura ") == roles.INFRA
    assert roles.normalize("Desarrollador") == roles.DEVELOPER
    assert roles.normalize("auditor") == "AUDITOR"


def _users():
    infra = NotifiedUser(uuid.uuid4(), "Ines", "ines@x.com", roles.INFRA, True)
    admin = NotifiedUser(uuid.uuid4(), "Ana", "ana@x.com", roles.ADMIN, True)
    dev = NotifiedUser(uuid.uuid4(), "Dani", "dani@x.com", roles.DEVELOPER, True)
    other_dev = NotifiedUser(uuid.uuid4(), "Otto", "otto@x.com", roles.DEVELOPER, True)
    inactive = NotifiedUser(uuid.uuid4(), "Inés2", "off@x.com", roles.INFRA, False)
    return infra, admin, dev, other_dev, inactive


def test_destinatarios_no_incluyen_a_quien_hizo_el_cambio_ni_inactivos():
    infra, admin, dev, other_dev, inactive = _users()
    request = NotifiedRequest(uuid.uuid4(), "DR-000001", "Cobranza", "Paquete", R.Pending, dev.id, None, 1, {}, None)
    got = composer.recipients(request, [infra, admin, dev, other_dev, inactive], [infra.id])
    assert [u.name for u in got] == ["Ana", "Dani"]  # Infra es el actor, Otto no tiene relación, Inés2 está inactiva


def test_un_correo_por_destinatario_con_los_cambios_agrupados():
    infra, admin, dev, *_ = _users()
    target_id = uuid.uuid4()
    request = NotifiedRequest(
        uuid.uuid4(), "DR-000007", "Cobranza", "Paquete 1", R.InProgress, dev.id, dev.id, 3,
        {target_id: "FESC (PRD)"}, None,
    )
    now = datetime.now(timezone.utc)
    changes = [
        DeploymentChange(ChangeKind.TargetStatusChanged, request.id, infra.id, now, target_id, T.Pending, T.InProgress, "Empezando"),
        DeploymentChange(ChangeKind.TargetStatusChanged, request.id, infra.id, now, target_id, T.InProgress, T.Applied),
    ]
    emails = composer.compose(request, changes, [infra, admin, dev], "https://hub.example.com/")
    assert sorted(e.to.name for e in emails) == ["Ana", "Dani"]
    assert emails[0].subject == "[DeploymentHub] DR-000007 · 2 cambios · en curso"
    body = emails[0].body
    assert "FESC (PRD): Pendiente → Aplicando (por Ines)." in body
    assert "Comentario: Empezando" in body
    assert f"https://hub.example.com/deployments/{request.id}" in body
    assert composer.compose(request, [], [infra], None) == []

"""Comportamientos transversales de la sesión: borrado lógico y auditoría automática."""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.base import EMPTY_GUID, AuditEntity, Entity, utcnow


@event.listens_for(Session, "do_orm_execute")
def _hide_deleted(state) -> None:
    """Los registros borrados (is_deleted) no aparecen en ninguna consulta.

    Se conservan en la base para no romper el historial de despliegues.
    Para verlos: execution_options(include_deleted=True).
    """
    if state.is_select and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(
            with_loader_criteria(Entity, lambda cls: cls.is_deleted.is_(False), include_aliases=True)
        )


@event.listens_for(Session, "before_flush")
def _stamp_audit(session: Session, flush_context, instances) -> None:
    """Llena created_at/created_by/updated_at/updated_by de forma automática al guardar."""
    now = utcnow()
    user_id = session.info.get("user_id") or EMPTY_GUID

    for obj in session.new:
        if isinstance(obj, AuditEntity):
            obj.created_at = now
            obj.created_by = user_id

    for obj in session.dirty:
        if isinstance(obj, AuditEntity) and session.is_modified(obj):
            obj.updated_at = now
            obj.updated_by = user_id

"""Reglas puras de estados: sin base de datos ni hora actual, para poder probarlas aisladas."""
from collections.abc import Collection, Sequence

from app.domain.enums import DeploymentRequestStatus as R
from app.domain.enums import DeploymentRequestTargetStatus as T

_FINISHED = {T.Applied, T.Failed, T.RolledBack}


def calculate_request_status(current: R, targets: Sequence[T]) -> R:
    """Estado general de una solicitud a partir de los estados de sus clientes destino."""
    # Borrador y cancelada los fija el usuario; los destinos no los cambian.
    if current in (R.Draft, R.Cancelled):
        return current

    # Los destinos cancelados u omitidos no cuentan para el resultado.
    active = [s for s in targets if s not in (T.Cancelled, T.Skipped)]

    if not active:
        return R.Completed if any(s == T.Skipped for s in targets) else R.Cancelled

    if all(s == T.Applied for s in active):
        return R.Completed

    if all(s in _FINISHED for s in active):
        return R.PartiallyCompleted if any(s == T.Applied for s in active) else R.Failed

    # Hay trabajo pendiente: si alguno ya arrancó o terminó, la solicitud está en curso.
    if any(s == T.InProgress or s in _FINISHED for s in active):
        return R.InProgress

    # Todos pendientes o programados: se conserva la aprobación si ya la tenía.
    return R.Approved if current == R.Approved else R.Pending


# Los despliegues hoy son manuales: se permite reportar el resultado sin pasar por InProgress.
_ALLOWED: dict[T, tuple[T, ...]] = {
    T.Pending: (T.Scheduled, T.InProgress, T.Applied, T.Failed, T.Cancelled, T.Skipped),
    T.Scheduled: (T.Pending, T.InProgress, T.Applied, T.Failed, T.Cancelled, T.Skipped),
    T.InProgress: (T.Applied, T.Failed),
    T.Applied: (T.RolledBack,),
    # Reintento de un cliente que falló o se revirtió.
    T.Failed: (T.Scheduled, T.InProgress, T.Applied, T.Skipped),
    T.RolledBack: (T.Scheduled, T.InProgress, T.Applied),
    T.Cancelled: (),
    T.Skipped: (),
}


def can_transition(from_status: T, to_status: T) -> bool:
    return to_status in _ALLOWED.get(from_status, ())


def next_statuses(from_status: T) -> Collection[T]:
    return _ALLOWED.get(from_status, ())

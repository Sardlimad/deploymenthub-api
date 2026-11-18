"""Cola de avisos en memoria y su envío en segundo plano.

Junta los cambios que llegan en `notifications_grouping_seconds` (una acción masiva sobre 20 clientes es
UN correo por persona, no 20) y, por solicitud, vuelve a leerla de la base para contar su estado final.
Si la API se reinicia con avisos en cola, esos avisos se pierden: el cambio ya quedó guardado y visible
en la aplicación. Registrar no envía nada ni espera: un fallo del SMTP nunca deshace el cambio.
"""
import logging
import queue
import threading
import time
import uuid
from collections import defaultdict

from app import repositories as repo
from app.config import Settings
from app.db import new_session
from app.domain import roles as role_names
from app.models import DeploymentRequest
from app.notifications import composer
from app.notifications.composer import DeploymentChange, NotifiedRequest, NotifiedUser
from app.notifications.email import EmailSender

logger = logging.getLogger("deploymenthub.notifications")


class DeploymentEmailQueue:
    def __init__(self, settings: Settings, email: EmailSender) -> None:
        self._settings = settings
        self._email = email
        self._queue: "queue.Queue[DeploymentChange]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enqueue(self, change: DeploymentChange) -> None:
        if self._settings.notifications_enabled:
            self._queue.put(change)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="deployment-email-queue")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        grouping = min(max(self._settings.notifications_grouping_seconds, 0), 60)
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            # Llegó el primero: se espera un momento para juntar los que vengan detrás.
            time.sleep(grouping)
            batch = [first]
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            by_request: dict[uuid.UUID, list[DeploymentChange]] = defaultdict(list)
            for change in batch:
                by_request[change.request_id].append(change)

            for request_id, changes in by_request.items():
                try:
                    self._send(request_id, changes)
                except Exception:  # noqa: BLE001
                    logger.exception("No se pudieron enviar los avisos de la solicitud %s.", request_id)

    def _send(self, request_id: uuid.UUID, changes: list[DeploymentChange]) -> None:
        db = new_session()
        try:
            request = repo.get_request(db, request_id)
            if request is None:
                return
            users = [
                NotifiedUser(u.id, u.name, u.email, role_names.normalize(u.role.name if u.role else ""), u.is_active)
                for u in repo.list_users(db)
            ]
            emails = composer.compose(_to_notified(request), changes, users, self._settings.notifications_public_url)
            for e in emails:
                self._email.send(e.to.email, e.subject, e.body)
            logger.info(
                "Avisos de %s: %d cambio(s), %d correo(s).", request.display_number, len(changes), len(emails)
            )
        finally:
            db.close()


def _to_notified(r: DeploymentRequest) -> NotifiedRequest:
    from app.models.base import EMPTY_GUID

    return NotifiedRequest(
        id=r.id,
        display_number=r.display_number,
        product_name=r.deployment_package.product.name if r.deployment_package and r.deployment_package.product else None,
        package_description=r.deployment_package.description if r.deployment_package else None,
        status=r.status,
        created_by_id=None if r.created_by == EMPTY_GUID else r.created_by,
        submitted_by_id=r.submitted_by,
        targets_total=len(r.targets),
        target_names={
            t.id: f"{t.installation.client.name} ({t.installation.product_environment.deployment_environment.code})"
            for t in r.targets
        },
        cancellation_reason=r.cancellation_reason,
    )

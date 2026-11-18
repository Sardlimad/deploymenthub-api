import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Uuid, BigInteger, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain import status as status_rules
from app.domain.enums import (
    ArtifactChangeType,
    ArtifactExecutionStatus,
    DeploymentRequestStatus,
    DeploymentRequestTargetStatus,
)
from app.domain.exceptions import DomainException
from app.models.base import AuditEntity, Base, Entity, IntEnumType, utcnow
from app.models.catalog import Client, ClientProductEnvironment, Product, ProductArtifact

_ACTIVE = text("is_deleted = false")

REQUEST_NUMBER_SEQUENCE = "deployment_request_numbers"


@dataclass(frozen=True)
class PackageSource:
    """Datos del repositorio de los que sale el paquete."""

    repository_id: str | None = None
    branch: str | None = None
    commit_id: str | None = None
    commit_author: str | None = None
    commit_message: str | None = None
    commit_date: datetime | None = None
    package_url: str | None = None


@dataclass(frozen=True)
class ArtifactResultInput:
    """Resultado reportado para un artefacto del paquete en un cliente."""

    package_artifact_id: uuid.UUID
    status: ArtifactExecutionStatus
    message: str | None = None


class Ticket(AuditEntity):
    __tablename__ = "tickets"
    __table_args__ = (Index("ux_tickets_name", "name", unique=True, postgresql_where=_ACTIVE),)

    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.is_active = True


deployment_request_tickets = Table(
    "deployment_request_tickets",
    Base.metadata,
    Column("deployment_request_id", Uuid, ForeignKey("deployment_requests.id", ondelete="CASCADE"), primary_key=True),
    Column("ticket_id", Uuid, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
)


class DeploymentPackage(AuditEntity):
    """Paquete de actualización de un producto: el conjunto ordenado de artefactos que se ejecuta en cada cliente.

    Se bloquea cuando una solicitud que lo usa se envía, para que lo desplegado no cambie después.
    Un paquete personalizado (custom_client_id) va solo a un cliente: no cambia la versión vigente
    de nadie ni hace que otros clientes aparezcan desactualizados.
    """

    __tablename__ = "deployment_packages"
    __table_args__ = (
        Index("ix_deployment_packages_product", "product_id"),
        Index("ix_deployment_packages_commit", "commit_id"),
        Index("ix_deployment_packages_created_at", "created_at"),
        Index("ix_deployment_packages_custom_client", "custom_client_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(String(500))

    # Origen en el repositorio. Opcional mientras los paquetes se arman a mano.
    repository_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commit_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    commit_author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commit_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    commit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    package_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Cliente al que va dirigido un paquete personalizado. None = paquete general del producto.
    custom_client_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=True
    )

    product: Mapped[Product] = relationship()
    custom_client: Mapped[Client | None] = relationship()
    artifacts: Mapped[list["DeploymentPackageArtifact"]] = relationship(
        back_populates="deployment_package", cascade="all, delete-orphan"
    )

    def __init__(
        self,
        product_id: uuid.UUID,
        description: str,
        source: PackageSource | None = None,
        custom_client_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__()
        self.product_id = product_id
        self.description = description
        self.custom_client_id = custom_client_id
        self.is_locked = False
        self.artifacts = []
        self._apply_source(source)

    @property
    def is_custom(self) -> bool:
        return self.custom_client_id is not None

    def update_info(self, description: str, source: PackageSource | None, custom_client_id: uuid.UUID | None) -> None:
        self._ensure_editable()

        # Cambiar el destinatario cambiaría qué versión de cada artefacto corresponde.
        if custom_client_id != self.custom_client_id and len(self.artifacts) > 0:
            raise DomainException(
                "Para cambiar el cliente de la actualización personalizada, quita primero sus artefactos."
            )

        self.description = description
        self.custom_client_id = custom_client_id
        if custom_client_id is None:
            self.custom_client = None
        self._apply_source(source)

    def allows_client(self, client_id: uuid.UUID) -> bool:
        """¿Este paquete puede enviarse a ese cliente?"""
        return not self.is_custom or self.custom_client_id == client_id

    def add_artifact(
        self,
        artifact: ProductArtifact,
        change_type: ArtifactChangeType,
        execution_order: int | None = None,
        notes: str | None = None,
    ) -> "DeploymentPackageArtifact":
        """Agrega un artefacto del catálogo al paquete.

        Para un artefacto que entra al catálogo con este paquete usar ArtifactChangeType.Added.
        """
        self._ensure_editable()

        if artifact.product_id != self.product_id:
            raise DomainException(f"El artefacto '{artifact.code}' pertenece a otro producto.")

        # RN-11: el paquete lleva la versión de su destinatario (la del cliente o la general).
        if not artifact.belongs_to(self.custom_client_id):
            raise DomainException(
                f"'{artifact.code}' es una versión personalizada: un paquete general debe llevar la versión general."
                if self.custom_client_id is None
                else f"'{artifact.code}' no es la versión de este cliente."
            )

        if any(a.product_artifact_id == artifact.id for a in self.artifacts):
            raise DomainException(f"El artefacto '{artifact.code}' ya está en el paquete.")

        if change_type == ArtifactChangeType.Added and not artifact.was_introduced_by(self.id):
            raise DomainException(
                f"El artefacto '{artifact.code}' ya existía en el catálogo; no puede marcarse como nuevo."
            )

        order = execution_order if execution_order is not None else (
            1 if not self.artifacts else max(a.execution_order for a in self.artifacts) + 1
        )
        package_artifact = DeploymentPackageArtifact(self.id, artifact, change_type, order, notes)
        self.artifacts.append(package_artifact)
        return package_artifact

    def update_artifact(self, package_artifact_id: uuid.UUID, execution_order: int, notes: str | None) -> None:
        self._ensure_editable()
        self.get_artifact(package_artifact_id).update(execution_order, notes)

    def remove_artifact(self, package_artifact_id: uuid.UUID) -> "DeploymentPackageArtifact":
        self._ensure_editable()
        package_artifact = self.get_artifact(package_artifact_id)
        self.artifacts.remove(package_artifact)
        return package_artifact

    def lock(self) -> None:
        self.is_locked = True

    def get_artifact(self, package_artifact_id: uuid.UUID) -> "DeploymentPackageArtifact":
        for a in self.artifacts:
            if a.id == package_artifact_id:
                return a
        raise DomainException("El artefacto no pertenece a este paquete.")

    def _ensure_editable(self) -> None:
        if self.is_locked:
            raise DomainException("El paquete ya fue enviado en una solicitud y no se puede modificar.")

    def _apply_source(self, source: PackageSource | None) -> None:
        s = source or PackageSource()
        self.repository_id = s.repository_id
        self.branch = s.branch
        self.commit_id = s.commit_id
        self.commit_author = s.commit_author
        self.commit_message = s.commit_message
        self.commit_date = s.commit_date
        self.package_url = s.package_url


class DeploymentPackageArtifact(AuditEntity):
    __tablename__ = "deployment_package_artifacts"
    __table_args__ = (
        Index("ux_deployment_package_artifacts_pkg_art", "deployment_package_id", "product_artifact_id", unique=True),
    )

    deployment_package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployment_packages.id", ondelete="CASCADE")
    )
    product_artifact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_artifacts.id", ondelete="RESTRICT")
    )
    change_type: Mapped[ArtifactChangeType] = mapped_column(IntEnumType(ArtifactChangeType))
    execution_order: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    deployment_package: Mapped[DeploymentPackage] = relationship(back_populates="artifacts")
    product_artifact: Mapped[ProductArtifact] = relationship()

    def __init__(
        self,
        deployment_package_id: uuid.UUID,
        product_artifact: ProductArtifact,
        change_type: ArtifactChangeType,
        execution_order: int,
        notes: str | None,
    ) -> None:
        super().__init__()
        self.deployment_package_id = deployment_package_id
        self.product_artifact_id = product_artifact.id
        self.product_artifact = product_artifact
        self.change_type = change_type
        self.execution_order = execution_order
        self.notes = notes

    @property
    def is_new(self) -> bool:
        """El artefacto entró al catálogo con este paquete."""
        return self.change_type == ArtifactChangeType.Added

    def update(self, execution_order: int, notes: str | None) -> None:
        self.execution_order = execution_order
        self.notes = notes


class DeploymentTargetStatusHistory(Entity):
    """Cada cambio de estado de un cliente destino, con quién y por qué."""

    __tablename__ = "deployment_target_status_history"
    __table_args__ = (Index("ix_deployment_target_status_history_target_changed", "deployment_request_target_id", "changed_at"),)

    deployment_request_target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployment_request_targets.id", ondelete="CASCADE")
    )
    from_status: Mapped[DeploymentRequestTargetStatus] = mapped_column(IntEnumType(DeploymentRequestTargetStatus))
    to_status: Mapped[DeploymentRequestTargetStatus] = mapped_column(IntEnumType(DeploymentRequestTargetStatus))
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __init__(
        self,
        target_id: uuid.UUID,
        from_status: DeploymentRequestTargetStatus,
        to_status: DeploymentRequestTargetStatus,
        comment: str | None,
        changed_by: uuid.UUID | None,
        changed_at: datetime,
    ) -> None:
        super().__init__()
        self.deployment_request_target_id = target_id
        self.from_status = from_status
        self.to_status = to_status
        self.comment = comment
        self.changed_by = changed_by
        self.changed_at = changed_at


class DeploymentTargetArtifactResult(Entity):
    """Resultado de un artefacto del paquete en un cliente: un script puede fallar en un cliente y en otro no.

    Guarda el último intento; el detalle de cada intento queda en el historial del destino.
    """

    __tablename__ = "deployment_target_artifact_results"
    __table_args__ = (
        Index(
            "ux_deployment_target_artifact_results_target_artifact",
            "deployment_request_target_id",
            "deployment_package_artifact_id",
            unique=True,
        ),
    )

    deployment_request_target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployment_request_targets.id", ondelete="CASCADE")
    )
    # Restrict: el resultado se borra junto con el destino, no con el artefacto del paquete.
    deployment_package_artifact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployment_package_artifacts.id", ondelete="RESTRICT")
    )
    status: Mapped[ArtifactExecutionStatus] = mapped_column(IntEnumType(ArtifactExecutionStatus))
    message: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, target_id: uuid.UUID, package_artifact_id: uuid.UUID) -> None:
        super().__init__()
        self.deployment_request_target_id = target_id
        self.deployment_package_artifact_id = package_artifact_id
        self.status = ArtifactExecutionStatus.Pending
        self.message = None
        self.attempt = 0
        self.executed_at = None

    def record(self, status: ArtifactExecutionStatus, message: str | None, attempt: int, now: datetime) -> None:
        self.status = status
        self.message = message
        self.attempt = attempt
        self.executed_at = now


class DeploymentRequestTarget(AuditEntity):
    """Un cliente destino de la solicitud. Tiene su propio estado, independiente del resto de clientes."""

    __tablename__ = "deployment_request_targets"
    __table_args__ = (
        Index("ux_deployment_request_targets_request_installation", "deployment_request_id", "client_product_environment_id", unique=True),
        Index("ix_deployment_request_targets_installation", "client_product_environment_id"),
        Index("ix_deployment_request_targets_status", "status"),
    )

    deployment_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployment_requests.id", ondelete="CASCADE")
    )
    client_product_environment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("client_product_environments.id", ondelete="RESTRICT")
    )
    status: Mapped[DeploymentRequestTargetStatus] = mapped_column(IntEnumType(DeploymentRequestTargetStatus))
    error_comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Paquete que tenía la instalación antes de aplicar este, para poder revertir.
    previous_package_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    previous_package_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deployment_request: Mapped["DeploymentRequest"] = relationship(back_populates="targets")
    installation: Mapped[ClientProductEnvironment] = relationship(foreign_keys=[client_product_environment_id])
    history: Mapped[list[DeploymentTargetStatusHistory]] = relationship(cascade="all, delete-orphan")
    artifact_results: Mapped[list[DeploymentTargetArtifactResult]] = relationship(cascade="all, delete-orphan")

    def __init__(self, deployment_request_id: uuid.UUID, installation: ClientProductEnvironment) -> None:
        super().__init__()
        self.deployment_request_id = deployment_request_id
        self.client_product_environment_id = installation.id
        self.installation = installation
        self.status = DeploymentRequestTargetStatus.Pending
        self.attempts = 0
        self.error_comment = None
        self.started_at = None
        self.finished_at = None
        self.previous_package_id = None
        self.previous_package_applied_at = None
        self.history = []
        self.artifact_results = []

    def change_status(
        self,
        new_status: DeploymentRequestTargetStatus,
        comment: str | None,
        changed_by: uuid.UUID | None,
        now: datetime,
    ) -> None:
        T = DeploymentRequestTargetStatus
        if new_status == self.status:
            raise DomainException(f"El destino ya está en estado {self.status.name}.")

        if not status_rules.can_transition(self.status, new_status):
            raise DomainException(f"No se puede pasar un destino de {self.status.name} a {new_status.name}.")

        if new_status == T.Failed and not (comment or "").strip():
            raise DomainException("Indica el motivo del fallo.")

        previous = self.status
        self.status = new_status

        if new_status == T.InProgress:
            self.attempts += 1
            self.started_at = now
            self.finished_at = None
            self.error_comment = None
        elif new_status == T.Applied:
            if previous != T.InProgress:
                self.attempts += 1
                self.started_at = self.started_at or now
            self.finished_at = now
            self.error_comment = None
        elif new_status == T.Failed:
            if previous != T.InProgress:
                self.attempts += 1
                self.started_at = self.started_at or now
            self.finished_at = now
            self.error_comment = comment
        elif new_status == T.RolledBack:
            self.finished_at = now
            self.error_comment = comment
        elif new_status in (T.Scheduled, T.Pending):
            self.finished_at = None

        self.history.append(DeploymentTargetStatusHistory(self.id, previous, new_status, comment, changed_by, now))

    def remember_previous_package(self, package_id: uuid.UUID | None, applied_at: datetime | None) -> None:
        self.previous_package_id = package_id
        self.previous_package_applied_at = applied_at

    def record_artifact_result(
        self,
        package_artifact_id: uuid.UUID,
        status: ArtifactExecutionStatus,
        message: str | None,
        now: datetime,
    ) -> None:
        result = next((r for r in self.artifact_results if r.deployment_package_artifact_id == package_artifact_id), None)
        if result is None:
            result = DeploymentTargetArtifactResult(self.id, package_artifact_id)
            self.artifact_results.append(result)
        result.record(status, message, self.attempts, now)


class DeploymentRequest(AuditEntity):
    """Solicitud de despliegue: un paquete enviado a N clientes destino.

    Raíz de agregado: los destinos y sus estados solo cambian a través de esta clase,
    que recalcula el estado general cada vez.
    """

    __tablename__ = "deployment_requests"
    __table_args__ = (
        Index("ux_deployment_requests_number", "request_number", unique=True),
        Index("ix_deployment_requests_status", "status"),
        Index("ix_deployment_requests_package", "deployment_package_id"),
    )

    request_number: Mapped[int] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[DeploymentRequestStatus] = mapped_column(IntEnumType(DeploymentRequestStatus))

    deployment_package_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("deployment_packages.id", ondelete="RESTRICT"), nullable=True
    )
    deployment_package: Mapped[DeploymentPackage | None] = relationship()

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    tickets: Mapped[list[Ticket]] = relationship(secondary=deployment_request_tickets)
    targets: Mapped[list[DeploymentRequestTarget]] = relationship(
        back_populates="deployment_request", cascade="all, delete-orphan"
    )

    def __init__(self, request_number: int) -> None:
        super().__init__()
        self.request_number = request_number
        self.status = DeploymentRequestStatus.Draft
        self.comment = None
        self.deployment_package_id = None
        self.deployment_package = None
        self.tickets = []
        self.targets = []

    @staticmethod
    def create(request_number: int) -> "DeploymentRequest":
        return DeploymentRequest(request_number)

    @staticmethod
    def format_number(request_number: int) -> str:
        return f"DR-{request_number:06d}"

    @property
    def display_number(self) -> str:
        return self.format_number(self.request_number)

    def update(self, comment: str | None, tickets: Sequence[Ticket]) -> None:
        self._ensure_draft("editar")
        self.comment = comment
        self.tickets = list(tickets)

    def associate_package(self, package: DeploymentPackage) -> None:
        self._ensure_draft("cambiar el paquete de")

        if self.targets and self.deployment_package is not None and self.deployment_package.product_id != package.product_id:
            raise DomainException("La solicitud ya tiene clientes de otro producto. Quítalos antes de cambiar el paquete.")

        if any(not package.allows_client(t.installation.client_id) for t in self.targets):
            raise DomainException(
                "El paquete es personalizado para otro cliente. Quita los clientes que no corresponden antes de asociarlo."
            )

        self.deployment_package_id = package.id
        self.deployment_package = package

    def add_target(self, installation: ClientProductEnvironment) -> DeploymentRequestTarget:
        self._ensure_draft("agregar clientes a")

        if self.deployment_package is None:
            raise DomainException("Asocia un paquete antes de elegir los clientes.")

        if installation.product_environment.product_id != self.deployment_package.product_id:
            raise DomainException("El cliente elegido no tiene contratado el producto del paquete.")

        if not self.deployment_package.allows_client(installation.client_id):
            raise DomainException("El paquete es una actualización personalizada para otro cliente.")

        if not installation.is_active:
            raise DomainException("La instalación del cliente está inactiva.")

        if any(t.client_product_environment_id == installation.id for t in self.targets):
            raise DomainException("El cliente ya es destino de esta solicitud.")

        target = DeploymentRequestTarget(self.id, installation)
        self.targets.append(target)
        return target

    def remove_target(self, target_id: uuid.UUID) -> None:
        self._ensure_draft("quitar clientes de")
        self.targets.remove(self.get_target(target_id))

    def submit(self, user_id: uuid.UUID | None, now: datetime) -> None:
        self._ensure_draft("enviar")

        if self.deployment_package is None:
            raise DomainException("La solicitud no tiene paquete.")

        if len(self.deployment_package.artifacts) == 0:
            raise DomainException("El paquete no tiene artefactos.")

        if not self.targets:
            raise DomainException("La solicitud no tiene clientes destino.")

        # El paquete pudo cambiar de cliente después de elegir los destinos.
        if any(not self.deployment_package.allows_client(t.installation.client_id) for t in self.targets):
            raise DomainException("Hay clientes que no corresponden a esta actualización personalizada.")

        self.deployment_package.lock()
        self.status = DeploymentRequestStatus.Pending
        self.submitted_at = now
        self.submitted_by = user_id

    def approve(self, user_id: uuid.UUID | None, now: datetime) -> None:
        if self.status != DeploymentRequestStatus.Pending:
            raise DomainException("Solo se puede aprobar una solicitud enviada que aún no empezó.")

        self.status = DeploymentRequestStatus.Approved
        self.approved_at = now
        self.approved_by = user_id

    def cancel(self, reason: str | None, user_id: uuid.UUID | None, now: datetime) -> None:
        R = DeploymentRequestStatus
        T = DeploymentRequestTargetStatus
        if self.status in (R.Completed, R.PartiallyCompleted, R.Failed, R.Cancelled):
            raise DomainException("La solicitud ya terminó y no se puede cancelar.")

        if any(t.status == T.InProgress for t in self.targets):
            raise DomainException("Hay clientes con el despliegue en curso. Espera su resultado antes de cancelar.")

        was_draft = self.status == R.Draft

        for target in [t for t in self.targets if t.status in (T.Pending, T.Scheduled)]:
            target.change_status(T.Cancelled, reason, user_id, now)

        self.cancellation_reason = reason
        self.cancelled_at = now

        # Si ningún cliente llegó a desplegarse la solicitud queda cancelada;
        # si alguno ya terminó, el estado general refleja lo que sí se hizo.
        self.status = R.Cancelled if was_draft else status_rules.calculate_request_status(
            R.Pending, [t.status for t in self.targets]
        )

        if self.status != R.Cancelled:
            self.completed_at = now

    def change_target_status(
        self,
        target_id: uuid.UUID,
        new_status: DeploymentRequestTargetStatus,
        comment: str | None,
        artifact_results: Collection[ArtifactResultInput] | None,
        user_id: uuid.UUID | None,
        now: datetime,
    ) -> DeploymentRequestTarget:
        """Cambia el estado de un cliente destino, registra los resultados por artefacto,
        actualiza el paquete vigente de la instalación y recalcula el estado general."""
        R = DeploymentRequestStatus
        T = DeploymentRequestTargetStatus
        if self.status in (R.Draft, R.Cancelled):
            raise DomainException("La solicitud no está enviada.")

        package = self.deployment_package
        if package is None:
            raise DomainException("La solicitud no tiene paquete.")

        target = self.get_target(target_id)
        results = list(artifact_results or [])

        for result in results:
            package.get_artifact(result.package_artifact_id)

        if new_status == T.Applied and any(r.status == ArtifactExecutionStatus.Failed for r in results):
            raise DomainException("Hay artefactos fallidos: el cliente no puede quedar como aplicado.")

        target.change_status(new_status, comment, user_id, now)

        for result in results:
            target.record_artifact_result(result.package_artifact_id, result.status, result.message, now)

        installation = target.installation

        if new_status == T.Applied:
            # Si no se detallaron resultados, todos los artefactos sin resultado se dan por aplicados.
            reported = {r.package_artifact_id for r in results}
            for artifact in [a for a in package.artifacts if a.id not in reported]:
                target.record_artifact_result(artifact.id, ArtifactExecutionStatus.Applied, None, now)

            # Un paquete personalizado no es una versión del producto: la vigente del cliente no cambia.
            if not package.is_custom:
                target.remember_previous_package(installation.current_package_id, installation.current_package_applied_at)
                installation.register_applied_package(package.id, now)
        elif (
            new_status == T.RolledBack
            and not package.is_custom
            and installation.current_package_id == package.id
        ):
            installation.restore_package(target.previous_package_id, target.previous_package_applied_at)

        self._recalculate_status(now)
        return target

    def get_target(self, target_id: uuid.UUID) -> DeploymentRequestTarget:
        for t in self.targets:
            if t.id == target_id:
                return t
        raise DomainException("El cliente destino no pertenece a esta solicitud.")

    def _recalculate_status(self, now: datetime) -> None:
        R = DeploymentRequestStatus
        self.status = status_rules.calculate_request_status(self.status, [t.status for t in self.targets])
        self.completed_at = now if self.status in (R.Completed, R.PartiallyCompleted, R.Failed) else None

    def _ensure_draft(self, action: str) -> None:
        if self.status != DeploymentRequestStatus.Draft:
            raise DomainException(f"No se puede {action} una solicitud que ya fue enviada.")

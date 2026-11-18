import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import ProductArtifactType
from app.models.base import AuditEntity, IntEnumType

_ACTIVE = text("is_deleted = false")


class Client(AuditEntity):
    __tablename__ = "clients"
    __table_args__ = (Index("ux_clients_code", "code", unique=True, postgresql_where=_ACTIVE),)

    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str] = mapped_column(String(30))
    is_on_premise: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    def __init__(self, name: str, code: str, is_on_premise: bool) -> None:
        super().__init__()
        self.name = name
        self.code = code.upper()
        self.is_on_premise = is_on_premise
        self.is_active = True

    def update(self, name: str, code: str, is_on_premise: bool) -> None:
        self.name = name
        self.code = code.upper()
        self.is_on_premise = is_on_premise

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


class DeploymentEnvironment(AuditEntity):
    __tablename__ = "deployment_environments"
    __table_args__ = (Index("ux_deployment_environments_code", "code", unique=True, postgresql_where=_ACTIVE),)

    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    def __init__(self, name: str, code: str) -> None:
        super().__init__()
        self.name = name
        self.code = code.upper()
        self.is_active = True

    def update(self, name: str, code: str) -> None:
        self.name = name
        self.code = code.upper()

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


class Product(AuditEntity):
    __tablename__ = "products"
    __table_args__ = (Index("ux_products_code", "code", unique=True, postgresql_where=_ACTIVE),)

    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    product_environments: Mapped[list["ProductEnvironment"]] = relationship(back_populates="product")

    def __init__(self, name: str, code: str) -> None:
        super().__init__()
        self.name = name
        self.code = code.upper()
        self.is_active = True

    def update(self, name: str, code: str) -> None:
        self.name = name
        self.code = code.upper()

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


class ProductEnvironment(AuditEntity):
    """Un producto existe en un ambiente (ej: Cobranza en PRODUCCIÓN)."""

    __tablename__ = "product_environments"
    __table_args__ = (
        Index(
            "ux_product_environments_product_environment",
            "product_id",
            "deployment_environment_id",
            unique=True,
            postgresql_where=_ACTIVE,
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="RESTRICT"))
    deployment_environment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployment_environments.id", ondelete="RESTRICT")
    )
    base_url: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    product: Mapped[Product] = relationship(back_populates="product_environments")
    deployment_environment: Mapped[DeploymentEnvironment] = relationship()
    installations: Mapped[list["ClientProductEnvironment"]] = relationship(back_populates="product_environment")

    def __init__(self, product_id: uuid.UUID, deployment_environment_id: uuid.UUID, base_url: str) -> None:
        super().__init__()
        self.product_id = product_id
        self.deployment_environment_id = deployment_environment_id
        self.base_url = base_url
        self.is_active = True

    def update(self, base_url: str) -> None:
        self.base_url = base_url

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


class ClientProductEnvironment(AuditEntity):
    """Instalación: un cliente con un producto contratado en un ambiente.

    Es la unidad a la que se despliega y la que guarda qué paquete tiene aplicado.
    """

    __tablename__ = "client_product_environments"
    __table_args__ = (
        Index(
            "ux_client_product_environments_client_pe",
            "client_id",
            "product_environment_id",
            unique=True,
            postgresql_where=_ACTIVE,
        ),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clients.id", ondelete="RESTRICT"))
    product_environment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_environments.id", ondelete="RESTRICT")
    )
    base_url: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    # Último paquete aplicado con éxito en esta instalación.
    current_package_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("deployment_packages.id", ondelete="RESTRICT"), nullable=True
    )
    current_package_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship()
    product_environment: Mapped[ProductEnvironment] = relationship(back_populates="installations")
    current_package: Mapped["DeploymentPackage | None"] = relationship("DeploymentPackage", foreign_keys=[current_package_id])

    def __init__(self, client_id: uuid.UUID, product_environment_id: uuid.UUID, base_url: str | None) -> None:
        super().__init__()
        self.client_id = client_id
        self.product_environment_id = product_environment_id
        self.base_url = base_url or ""
        self.is_active = True
        self.current_package_id = None
        self.current_package_applied_at = None

    def update(self, base_url: str | None) -> None:
        self.base_url = base_url or ""

    def register_applied_package(self, package_id: uuid.UUID, applied_at: datetime) -> None:
        self.current_package_id = package_id
        self.current_package_applied_at = applied_at

    def restore_package(self, package_id: uuid.UUID | None, applied_at: datetime | None) -> None:
        """Vuelve al paquete que tenía antes de un despliegue revertido."""
        self.current_package_id = package_id
        self.current_package_applied_at = applied_at

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


class ProductArtifact(AuditEntity):
    """Artefacto del catálogo de un producto.

    Puede haber varias VERSIONES con el mismo tipo y código: la general (owner_client_id None)
    y una personalizada por cliente (el «Rpt_Pagare» de FESC no es el mismo que el de UDV ni que el general).
    """

    __tablename__ = "product_artifacts"
    __table_args__ = (
        # En Postgres los NULL son distintos en un índice único: se separan en dos índices parciales
        # para que solo exista UNA versión general por tipo y código, y una por cliente.
        Index(
            "ux_product_artifacts_general",
            "product_id", "type", "code",
            unique=True,
            postgresql_where=text("is_deleted = false AND owner_client_id IS NULL"),
        ),
        Index(
            "ux_product_artifacts_owner",
            "product_id", "type", "code", "owner_client_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND owner_client_id IS NOT NULL"),
        ),
        Index("ix_product_artifacts_introduced_in_package", "introduced_in_package_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(200))
    type: Mapped[ProductArtifactType] = mapped_column(IntEnumType(ProductArtifactType))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Ruta del artefacto en el repositorio del producto (ej: Scripts/04.PROCEDIMIENTOS/usp_X.sql).
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Paquete con el que el artefacto entró al catálogo. None si se registró a mano.
    introduced_in_package_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("deployment_packages.id", ondelete="RESTRICT"), nullable=True
    )
    # Cliente dueño de esta versión personalizada. None = versión general del producto.
    owner_client_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    product: Mapped[Product] = relationship()
    owner_client: Mapped[Client | None] = relationship()

    def __init__(
        self,
        product_id: uuid.UUID,
        code: str,
        name: str,
        type: ProductArtifactType,
        description: str | None = None,
        path: str | None = None,
        introduced_in_package_id: uuid.UUID | None = None,
        owner_client_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__()
        self.product_id = product_id
        self.code = self.normalize_code(code)
        self.name = name
        self.type = ProductArtifactType(type)
        self.description = description
        self.path = path
        self.introduced_in_package_id = introduced_in_package_id
        self.owner_client_id = owner_client_id
        self.is_active = True

    @property
    def is_custom(self) -> bool:
        return self.owner_client_id is not None

    def belongs_to(self, owner_client_id: uuid.UUID | None) -> bool:
        """¿Es la versión que corresponde a ese dueño? (None = general)."""
        return self.owner_client_id == owner_client_id

    def update(
        self,
        code: str,
        name: str,
        type: ProductArtifactType,
        description: str | None,
        path: str | None,
    ) -> None:
        self.code = self.normalize_code(code)
        self.name = name
        self.type = ProductArtifactType(type)
        self.description = description
        self.path = path

    def was_introduced_by(self, package_id: uuid.UUID) -> bool:
        return self.introduced_in_package_id == package_id

    def create_version_for(self, owner_client_id: uuid.UUID | None, introduced_in_package_id: uuid.UUID) -> "ProductArtifact":
        """Crea la versión de otro dueño a partir de esta (misma identidad: tipo, código, nombre y ruta)."""
        return ProductArtifact(
            self.product_id, self.code, self.name, self.type, self.description, self.path,
            introduced_in_package_id, owner_client_id,
        )

    def make_general(self) -> None:
        """La versión personalizada pasa a ser la general del producto."""
        self.owner_client_id = None
        self.owner_client = None

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    @staticmethod
    def normalize_code(code: str) -> str:
        return code.strip().upper()


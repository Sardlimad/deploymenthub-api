"""Enumeraciones del dominio. Se guardan como entero y viajan por la API como texto ("Applied", "Failed"...)."""
from enum import IntEnum


class ArtifactChangeType(IntEnum):
    """Qué le hace un paquete a un artefacto. Added = el artefacto entra al catálogo con este paquete."""
    Added = 1
    Modified = 2
    Removed = 3


class ArtifactExecutionStatus(IntEnum):
    Pending = 1
    Applied = 2
    Failed = 3
    Skipped = 4


class DeploymentRequestStatus(IntEnum):
    """Salvo Draft, Approved y Cancelled (que fija el usuario) se calcula a partir de los destinos."""
    Draft = 1
    Pending = 2
    InProgress = 3
    Completed = 4
    PartiallyCompleted = 5
    Failed = 6
    Cancelled = 7
    Approved = 8


class DeploymentRequestTargetStatus(IntEnum):
    Pending = 1
    Scheduled = 2
    InProgress = 3
    Applied = 4
    Failed = 5
    Cancelled = 6
    Skipped = 7
    RolledBack = 8


class ProductArtifactType(IntEnum):
    Module = 1
    Service = 2
    StoredProcedure = 3
    Table = 4
    DataScript = 5
    View = 6
    Function = 7
    Trigger = 8
    Report = 9
    Configuration = 10
    Other = 99

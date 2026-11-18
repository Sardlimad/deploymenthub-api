"""Paquetes, solicitudes de despliegue y clientes destino."""
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.deps import current_user_id, get_db, require_auth, require_deployer, require_operator
from app.domain.exceptions import ValidationException
from app.routers import no_content
from app.schemas import (
    AddTargetsBody,
    CancelRequestBody,
    ChangeStatusBody,
    DeploymentPackageBody,
    DeploymentPackageDto,
    DeploymentRequestBody,
    DeploymentRequestDetailDto,
    DeploymentRequestSummaryDto,
    DeploymentTargetDto,
    PackageArtifactDto,
    PackageArtifactInput,
    PagedResult,
    UpdatePackageArtifactBody,
    parse_enum,
)
from app.domain.enums import DeploymentRequestStatus
from app.services import packages as package_service
from app.services import requests as request_service

auth = [Depends(require_auth)]
deployer = [Depends(require_deployer)]
operator = [Depends(require_operator)]

# ------------------------------------------------------------------------------------------------ paquetes
packages = APIRouter(prefix="/api/deploymentpackages", tags=["DeploymentPackages"], dependencies=auth)


@packages.get("", response_model=list[DeploymentPackageDto])
def list_packages(product_id: uuid.UUID | None = Query(default=None, alias="productId"), db: Session = Depends(get_db)):
    return package_service.list_packages(db, product_id)


@packages.get("/{id}", response_model=DeploymentPackageDto)
def get_package(id: uuid.UUID, db: Session = Depends(get_db)):
    return package_service.get_package(db, id)


@packages.post("", status_code=201, response_model=DeploymentPackageDto, dependencies=deployer)
def create_package(body: DeploymentPackageBody, db: Session = Depends(get_db)):
    """Crea el paquete con sus artefactos. Los artefactos que no existan en el catálogo del producto
    se agregan al catálogo y quedan marcados como nuevos (isNew = true)."""
    package = package_service.create_package(db, body)
    return JSONResponse(
        package.model_dump(by_alias=True, mode="json"),
        status_code=201,
        headers={"Location": f"/api/deploymentpackages/{package.id}"},
    )


@packages.put("/{id}", status_code=204, dependencies=deployer)
def update_package(id: uuid.UUID, body: DeploymentPackageBody, db: Session = Depends(get_db)):
    package_service.update_package(db, id, body)
    return no_content()


@packages.delete("/{id}", status_code=204, dependencies=deployer)
def delete_package(id: uuid.UUID, db: Session = Depends(get_db)):
    package_service.delete_package(db, id)
    return no_content()


# ---------------------------------------------------------------------------------- artefactos de un paquete
package_artifacts = APIRouter(
    prefix="/api/deploymentpackages/{package_id}/artifacts", tags=["DeploymentPackageArtifacts"], dependencies=auth
)


@package_artifacts.get("/{package_artifact_id}", response_model=PackageArtifactDto)
def get_package_artifact(package_id: uuid.UUID, package_artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    return package_service.get_package_artifact(db, package_id, package_artifact_id)


@package_artifacts.post("", status_code=201, response_model=PackageArtifactDto, dependencies=deployer)
def create_package_artifact(package_id: uuid.UUID, body: PackageArtifactInput, db: Session = Depends(get_db)):
    """Artefactos dentro de un paquete. Solo se pueden cambiar mientras el paquete no se haya enviado."""
    artifact = package_service.add_package_artifact(db, package_id, body)
    return JSONResponse(
        artifact.model_dump(by_alias=True, mode="json"),
        status_code=201,
        headers={"Location": f"/api/deploymentpackages/{package_id}/artifacts/{artifact.id}"},
    )


@package_artifacts.put("/{package_artifact_id}", status_code=204, dependencies=deployer)
def update_package_artifact(
    package_id: uuid.UUID, package_artifact_id: uuid.UUID, body: UpdatePackageArtifactBody, db: Session = Depends(get_db)
):
    package_service.update_package_artifact(db, package_id, package_artifact_id, body)
    return no_content()


@package_artifacts.delete("/{package_artifact_id}", status_code=204, dependencies=deployer)
def delete_package_artifact(package_id: uuid.UUID, package_artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    package_service.delete_package_artifact(db, package_id, package_artifact_id)
    return no_content()


# -------------------------------------------------------------------------------------------- solicitudes
requests = APIRouter(prefix="/api/deploymentrequests", tags=["DeploymentRequests"], dependencies=auth)


def _parse_statuses(values: list[str] | None) -> list[DeploymentRequestStatus] | None:
    if not values:
        return None
    try:
        return [parse_enum(DeploymentRequestStatus, v) for v in values]
    except ValueError as ex:
        raise ValidationException({"Status": [str(ex)]}) from ex


@requests.get("", response_model=PagedResult[DeploymentRequestSummaryDto])
def search_requests(
    statuses: list[str] | None = Query(default=None, alias="status"),
    product_id: uuid.UUID | None = Query(default=None, alias="productId"),
    client_id: uuid.UUID | None = Query(default=None, alias="clientId"),
    search: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20, alias="pageSize"),
    mine: bool = Query(default=False),
    db: Session = Depends(get_db),
    user_id=Depends(current_user_id),
):
    """Busca solicitudes. status se puede repetir: ?status=Pending&status=InProgress."""
    return request_service.search_requests(
        db, user_id, _parse_statuses(statuses), product_id, client_id, search, page, page_size, mine
    )


@requests.get("/{id}", response_model=DeploymentRequestDetailDto)
def get_request(id: uuid.UUID, db: Session = Depends(get_db)):
    return request_service.get_request(db, id)


@requests.post("", status_code=201, response_model=DeploymentRequestDetailDto, dependencies=deployer)
def create_request(body: DeploymentRequestBody | None = None, db: Session = Depends(get_db)):
    request = request_service.create_request(db, body)
    return JSONResponse(
        request.model_dump(by_alias=True, mode="json"),
        status_code=201,
        headers={"Location": f"/api/deploymentrequests/{request.id}"},
    )


@requests.put("/{id}", status_code=204, dependencies=deployer)
def update_request(id: uuid.UUID, body: DeploymentRequestBody, db: Session = Depends(get_db)):
    request_service.update_request(db, id, body)
    return no_content()


@requests.put("/{request_id}/package/{package_id}", status_code=204, dependencies=deployer)
def associate_package(request_id: uuid.UUID, package_id: uuid.UUID, db: Session = Depends(get_db)):
    request_service.associate_package(db, request_id, package_id)
    return no_content()


@requests.post("/{request_id}/submit", status_code=204, dependencies=deployer)
def submit(request_id: uuid.UUID, db: Session = Depends(get_db), user_id=Depends(current_user_id)):
    request_service.submit_request(db, request_id, user_id)
    return no_content()


@requests.post("/{request_id}/approve", status_code=204, dependencies=operator)
def approve(request_id: uuid.UUID, db: Session = Depends(get_db), user_id=Depends(current_user_id)):
    request_service.approve_request(db, request_id, user_id)
    return no_content()


@requests.post("/{request_id}/cancel", status_code=204, dependencies=deployer)
def cancel(
    request_id: uuid.UUID,
    body: CancelRequestBody | None = None,
    db: Session = Depends(get_db),
    user_id=Depends(current_user_id),
):
    request_service.cancel_request(db, request_id, body.reason if body else None, user_id)
    return no_content()


# ------------------------------------------------------------------------------------------------ destinos
targets = APIRouter(prefix="/api/deploymentrequests/{request_id}/targets", tags=["DeploymentTargets"], dependencies=auth)


@targets.get("/{target_id}", response_model=DeploymentTargetDto)
def get_target(request_id: uuid.UUID, target_id: uuid.UUID, db: Session = Depends(get_db)):
    return request_service.get_target(db, request_id, target_id)


@targets.post("", response_model=list[DeploymentTargetDto], dependencies=deployer)
def add_targets(request_id: uuid.UUID, body: AddTargetsBody, db: Session = Depends(get_db)):
    """Agrega clientes destino (ids de instalación) a una solicitud en borrador."""
    return request_service.add_targets(db, request_id, body)


@targets.delete("/{target_id}", status_code=204, dependencies=deployer)
def remove_target(request_id: uuid.UUID, target_id: uuid.UUID, db: Session = Depends(get_db)):
    request_service.remove_target(db, request_id, target_id)
    return no_content()


@targets.put("/{target_id}/status", response_model=DeploymentRequestDetailDto, dependencies=operator)
def change_status(
    request_id: uuid.UUID,
    target_id: uuid.UUID,
    body: ChangeStatusBody,
    db: Session = Depends(get_db),
    user_id=Depends(current_user_id),
):
    """Reporta el estado de un cliente. Devuelve la solicitud completa con el estado general recalculado."""
    return request_service.change_target_status(db, request_id, target_id, body, user_id)


all_routers = [packages, package_artifacts, requests, targets]

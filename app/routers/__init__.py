import uuid

from fastapi.responses import JSONResponse, Response


def no_content() -> Response:
    return Response(status_code=204)


def created(id: uuid.UUID, location: str) -> JSONResponse:
    """201 con el id como cuerpo JSON (un GUID entre comillas) y la cabecera Location."""
    return JSONResponse(str(id), status_code=201, headers={"Location": location})

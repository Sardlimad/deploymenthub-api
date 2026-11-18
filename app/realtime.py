"""Tiempo real de despliegues: replica el hub de SignalR del backend original (/hubs/deployments),
para que el frontend (@microsoft/signalr) se conecte sin cambios.

Protocolo (JSON): POST /hubs/deployments/negotiate → WebSocket con handshake {"protocol":"json","version":1}
y mensajes separados por el carácter 0x1E. El servidor envía cada evento como una invocación
"deploymentEvent" y un ping cada 15 s (el cliente corta si pasan 30 s sin recibir nada).
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app.security import Principal, TokenError, decode_access_token

logger = logging.getLogger("deploymenthub.realtime")

HUB_PATH = "/hubs/deployments"
EVENT_METHOD = "deploymentEvent"
RS = "\x1e"  # separador de mensajes del protocolo de SignalR

PING_INTERVAL_SECONDS = 15


class EventTypes:
    DEPLOYMENT_CREATED = "deployment.created"
    DEPLOYMENT_UPDATED = "deployment.updated"
    DEPLOYMENT_SUBMITTED = "deployment.submitted"
    DEPLOYMENT_STATUS_CHANGED = "deployment.status_changed"
    TARGET_STATUS_CHANGED = "target.status_changed"
    ARTIFACT_ADDED_TO_CATALOG = "artifact.added_to_catalog"
    INSTALLATION_UPDATED = "installation.updated"


@dataclass
class RealtimeEvent:
    type: str
    request_id: uuid.UUID | None
    payload: Any
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json_dict(self) -> dict:
        return {
            "type": self.type,
            "requestId": str(self.request_id) if self.request_id else None,
            "occurredAt": self.occurred_at.isoformat(),
            "payload": _jsonable(self.payload),
        }


def _jsonable(value: Any) -> Any:
    """Los payloads llevan DTOs (camelCase, enums como texto), UUID y fechas."""
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, mode="json")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "name") and hasattr(value, "value") and isinstance(value.value, int):  # IntEnum
        return value.name
    return value


class DeploymentsHub:
    """Conexiones abiertas. Cada evento se envía a todas, como Clients.All."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def publish(self, event: RealtimeEvent) -> None:
        """Se llama DESPUÉS de guardar, desde los endpoints (hilos). Un fallo al avisar nunca debe convertir
        la operación en error: el cambio ya se guardó."""
        try:
            if self._loop is None or not self._connections:
                return
            message = self._frame(
                {"type": 1, "target": EVENT_METHOD, "arguments": [event.to_json_dict()]}
            )
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo publicar el evento %s", event.type, exc_info=True)

    async def _broadcast(self, message: str) -> None:
        for connection in list(self._connections):
            try:
                await connection.send_text(message)
            except Exception:  # noqa: BLE001
                self._connections.discard(connection)

    @staticmethod
    def _frame(payload: dict) -> str:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + RS

    async def handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            # Handshake: el cliente declara el protocolo.
            handshake = await asyncio.wait_for(websocket.receive_text(), timeout=15)
            request = json.loads(handshake.split(RS)[0])
            if request.get("protocol") != "json":
                await websocket.send_text(self._frame({"error": "Solo se admite el protocolo json."}))
                await websocket.close()
                return
            await websocket.send_text(self._frame({}))
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
            await _safe_close(websocket)
            return

        self._connections.add(websocket)
        pinger = asyncio.create_task(self._ping_loop(websocket))
        try:
            while True:
                data = await websocket.receive_text()
                for raw in data.split(RS):
                    if not raw:
                        continue
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        continue
                    if message.get("type") == 7:  # Close
                        return
                    # Ping (6) y el resto se ignoran: el hub no expone métodos al cliente.
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Conexión de tiempo real cerrada con error", exc_info=True)
        finally:
            pinger.cancel()
            self._connections.discard(websocket)
            await _safe_close(websocket)

    async def _ping_loop(self, websocket: WebSocket) -> None:
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                await websocket.send_text(self._frame({"type": 6}))
        except Exception:  # noqa: BLE001
            return


async def _safe_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except Exception:  # noqa: BLE001
        pass


hub = DeploymentsHub()
router = APIRouter()


def _principal_from(token: str | None) -> Principal | None:
    if not token:
        return None
    try:
        return decode_access_token(get_settings(), token)
    except TokenError:
        return None


def _bearer(headers) -> str | None:
    value = headers.get("authorization", "")
    return value[7:].strip() if value.lower().startswith("bearer ") else None


@router.post(HUB_PATH + "/negotiate")
async def negotiate(request: Request) -> Response:
    """Primer paso de SignalR. El hub exige sesión; solo se ofrece WebSockets."""
    token = _bearer(request.headers) or request.query_params.get("access_token")
    if _principal_from(token) is None:
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    connection_token = uuid.uuid4().hex
    return JSONResponse(
        {
            "negotiateVersion": 1,
            "connectionId": uuid.uuid4().hex,
            "connectionToken": connection_token,
            "availableTransports": [{"transport": "WebSockets", "transferFormats": ["Text", "Binary"]}],
        }
    )


@router.websocket(HUB_PATH)
async def deployments_socket(websocket: WebSocket) -> None:
    # El navegador no puede mandar cabeceras en el WebSocket: el token llega como access_token.
    token = websocket.query_params.get("access_token") or _bearer(websocket.headers)
    if _principal_from(token) is None:
        await websocket.close(code=1008)
        return
    await hub.handle(websocket)

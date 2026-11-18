"""DeploymentHub API (Python / FastAPI / PostgreSQL). Mismas rutas y contratos que el backend .NET original."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import realtime
from app.config import get_settings, validate_required
from app.db import new_session
from app.errors import register_error_handlers, unhandled_exception_response
from app.routers import auth, catalog, deployments, identity, krud
from app.seed import seed_identity
from app.state import get_krud_signer, get_notification_queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("deploymenthub")


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.attributes["skip_logging"] = True  # no pisar la configuración de logs de la API
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_required(settings)
    get_krud_signer()  # falla al arrancar si la clave de KRUD es inválida

    if settings.run_migrations:
        # Alembic es síncrono: se ejecuta fuera del bucle de eventos.
        await asyncio.to_thread(run_migrations)

    def _seed() -> None:
        db = new_session()
        try:
            seed_identity(db, settings)
        finally:
            db.close()

    await asyncio.to_thread(_seed)

    realtime.hub.bind_loop(asyncio.get_running_loop())
    queue = get_notification_queue()
    queue.start()
    logger.info("%s %s lista.", settings.application_name, settings.application_version)
    try:
        yield
    finally:
        queue.stop()


class NormalizePathMiddleware:
    """ASP.NET enruta sin distinguir mayúsculas ni la barra final (/api/Clients = /api/clients/) y el frontend
    lo aprovecha: aquí se normaliza la ruta antes de enrutar."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope["path"]
            if path.lower().startswith(("/api/", "/hubs/")):
                normalized = path.lower().rstrip("/")
                if normalized != path:
                    scope = dict(scope)
                    scope["path"] = normalized
                    if scope.get("raw_path"):
                        scope["raw_path"] = normalized.encode()
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DeploymentHub API",
        version=settings.application_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.is_development else None,
    )

    register_error_handlers(app)

    @app.middleware("http")
    async def catch_all(request: Request, call_next):
        # Dentro de CORS: así hasta el 500 lleva las cabeceras CORS y el navegador puede leerlo.
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            return await unhandled_exception_response(request, exc)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(NormalizePathMiddleware)

    for router in (*catalog.all_routers, *identity.all_routers, *deployments.all_routers, auth.router, krud.router):
        app.include_router(router)
    app.include_router(realtime.router)

    @app.get("/health", tags=["Health"])
    def health():
        """Sondeo de vida para el hosting o el balanceador: responde sin sesión y sin consultar la base."""
        return {"status": "ok"}

    return app


app = create_app()

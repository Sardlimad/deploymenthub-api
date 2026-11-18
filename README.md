# DeploymentHub API (Python)

Backend de **DeploymentHub** en Python (FastAPI + SQLAlchemy + **PostgreSQL**), con las mismas rutas, reglas de negocio,
permisos, contratos JSON y tiempo real que el backend .NET original (`DeploymentHub_v2.0`). El frontend funciona sin cambios:
solo apunta `VITE_API_URL` a esta API.

> El backend .NET sigue intacto en su repositorio; este es un proyecto aparte, pensado para hospedarse gratis donde
> no hay servidor .NET.

## Qué replica

| Área | Detalle |
|---|---|
| Autenticación | Login con JWT (HS256), `me`, cambio de contraseña, recuperación por código de 6 dígitos (3 pasos), bloqueo tras 5 intentos fallidos (15 min), límite de 10 intentos/min por IP |
| Roles | `ADMIN` (todo), `DEVELOPER` (arma paquetes, crea/envía/cancela solicitudes), `INFRA` (aprueba y reporta resultados). Los nombres en español existentes («Administrador»…) equivalen a los códigos |
| Catálogos | Clientes, ambientes, productos, ambientes de producto, artefactos (versión general y personalizada por cliente), instalaciones y su estado de versión |
| Despliegues | Paquetes (con bloqueo al enviarse y actualizaciones personalizadas), solicitudes, destinos por cliente, historial, resultado por artefacto, estado general calculado, reversión |
| Tiempo real | Hub compatible con SignalR en `/hubs/deployments` (el cliente `@microsoft/signalr` del frontend se conecta tal cual) |
| Correo | Código de recuperación y avisos de cambios (agrupados por solicitud y destinatario) por SMTP |
| KRUD | `GET /api/krud/asercion`: aserción ES256 firmada con la sesión (apagada si no hay clave) |
| Errores | `ProblemDetails` (`application/problem+json`) con los mismos códigos: 400 validación, 401, 403, 404, 409 regla de negocio |

Detalles de compatibilidad: enums como texto (`"Applied"`), JSON en camelCase, rutas sin distinguir mayúsculas ni barra final
(`/api/Clients` = `/api/clients/`), borrado lógico y auditoría (`created_by`, `updated_at`…), Swagger en `/docs` (solo en `development`).

## Requisitos

- Python 3.11+
- PostgreSQL 13+ (en local sirve Docker, una instalación normal, o el que trae `pgserver` para las pruebas)

## Puesta en marcha local

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # y completa DATABASE_URL, JWT_KEY, SEED_ADMIN_*
uvicorn app.main:app --reload --port 5228
```

Al arrancar aplica las migraciones (`RUN_MIGRATIONS=true`), crea los roles y, si no hay administrador activo, el de
`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`. El puerto 5228 es el que el frontend espera por defecto
(`http://localhost:5228/api`).

Postgres rápido con Docker:

```bash
docker run -d --name dh-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=deploymenthub -p 5432:5432 postgres:16
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/deploymenthub
```

## Configuración (variables de entorno o `.env`)

Ver [.env.example](.env.example). Las imprescindibles: `DATABASE_URL`, `JWT_KEY` (≥ 32 bytes) y `CORS_ALLOWED_ORIGINS`.
La API no arranca si falta alguna o si queda un valor «COMPLETAR…».

## Migraciones

```bash
alembic upgrade head                                      # aplicar
alembic revision --autogenerate -m "describe el cambio"   # tras cambiar los modelos
```

## Pruebas

```bash
pytest
```

Levantan un PostgreSQL embebido (`pgserver`), así que no necesitan nada instalado. Con tu propio Postgres:
`TEST_DATABASE_URL=postgresql://... pytest` (base vacía y desechable). Cubren reglas de estado, el ciclo completo de una
solicitud, permisos por rol, paquetes personalizados, recuperación de contraseña, el protocolo de tiempo real, KRUD y avisos.

## Despliegue gratuito

1. **Base de datos**: crea un Postgres gratuito (Neon, Supabase…) y copia su cadena de conexión
   (`postgresql://...?sslmode=require`).
2. **API**: en Render (o Koyeb, Fly.io, Railway…) crea un servicio web desde este repositorio. Hay un `Dockerfile` y un
   `render.yaml` listos. Variables: `ENVIRONMENT=production`, `DATABASE_URL`, `JWT_KEY`, `CORS_ALLOWED_ORIGINS` (URL
   del frontend), `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, y opcionalmente correo (`EMAIL_*`) y `NOTIFICATIONS_PUBLIC_URL`.
3. **Frontend**: compílalo con `VITE_API_URL=https://tu-api.onrender.com/api`.

Importante en hosting gratuito:

- **Un solo proceso** (no uses varios workers): el tiempo real, la cola de avisos y el límite de intentos viven en memoria.
- Los planes gratuitos «duermen» el servicio tras un rato sin tráfico; la primera petición tarda unos segundos y los
  avisos en cola se pierden si el servicio se reinicia (el cambio ya quedó guardado).
- Sin `EMAIL_HOST`/`EMAIL_FROM` no sale ningún correo (en `development` se escribe en el log). La recuperación de
  contraseña los necesita; un ADMIN también puede definir la contraseña de un usuario desde Usuarios.

## Migrar datos desde el backend .NET

Este repositorio no copia datos de SQL Server. Los hashes de contraseña (BCrypt) son compatibles, así que al migrar las
tablas los usuarios conservan su contraseña. Los nombres de tablas y columnas son `snake_case` (ver `app/models`).

## Estructura

```
app/
  main.py            arranque, CORS, rutas, migraciones y seed
  config.py          configuración (variables de entorno)
  models/            entidades con sus reglas de negocio (dominio)
  domain/            enums, excepciones, roles y reglas puras de estados
  schemas.py         contratos de la API (DTOs)
  validation.py      validación con los mismos mensajes que el backend original
  repositories.py    consultas
  services/          casos de uso (catálogo, identidad, auth, paquetes, solicitudes)
  routers/           endpoints
  realtime.py        hub compatible con SignalR
  notifications/     correo, redacción de avisos y cola en segundo plano
  security.py        bcrypt, JWT y firmador de KRUD
migrations/          Alembic
tests/               pruebas
```

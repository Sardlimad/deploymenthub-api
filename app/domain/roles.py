"""Códigos de rol que usa la autorización.

Los roles se guardan por nombre; los nombres en español que ya existan
("Administrador", "Infraestructura", "Desarrollador") equivalen a estos códigos.
"""

ADMIN = "ADMIN"          # Administra catálogos, usuarios y puede hacer todo lo demás.
INFRA = "INFRA"          # Aplica los despliegues en los clientes y reporta su resultado.
DEVELOPER = "DEVELOPER"  # Arma paquetes y crea y envía solicitudes de despliegue.

ALL = (ADMIN, INFRA, DEVELOPER)

_ALIASES = {
    "admin": ADMIN,
    "administrador": ADMIN,
    "infra": INFRA,
    "infraestructura": INFRA,
    "developer": DEVELOPER,
    "desarrollador": DEVELOPER,
}


def normalize(role_name: str) -> str:
    """Devuelve el código del rol, o el nombre en mayúsculas si no es un rol conocido."""
    name = role_name.strip()
    return _ALIASES.get(name.lower(), name.upper())

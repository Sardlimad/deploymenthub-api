"""Validación de datos de entrada, con las mismas reglas y claves de error que el backend original (FluentValidation).

Las claves van en PascalCase ("Code", "Artifact.Type") y se devuelven en `errors` del ProblemDetails;
el frontend muestra el primer mensaje.
"""
import re
import uuid
from collections.abc import Sequence
from enum import IntEnum

from app.domain.exceptions import ValidationException

_EMPTY_GUID = uuid.UUID(int=0)


def humanize(prop: str) -> str:
    """'ProductId' → 'Product Id' (así nombra FluentValidation la propiedad en sus mensajes)."""
    last = re.sub(r"\[\d+\]", "", prop.split(".")[-1])
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last)


class Validator:
    def __init__(self) -> None:
        self.errors: dict[str, list[str]] = {}

    def add(self, prop: str, message: str) -> None:
        messages = self.errors.setdefault(prop, [])
        if message not in messages:
            messages.append(message)

    def not_empty(self, prop: str, value, message: str | None = None) -> None:
        empty = (
            value is None
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, uuid.UUID) and value == _EMPTY_GUID)
            or (isinstance(value, (list, tuple, set)) and len(value) == 0)
        )
        if empty:
            self.add(prop, message or f"'{humanize(prop)}' must not be empty.")

    def not_null(self, prop: str, value, message: str | None = None) -> None:
        if value is None:
            self.add(prop, message or f"'{humanize(prop)}' must not be empty.")

    def max_len(self, prop: str, value: str | None, maximum: int) -> None:
        if value is not None and len(value) > maximum:
            self.add(
                prop,
                f"The length of '{humanize(prop)}' must be {maximum} characters or fewer. "
                f"You entered {len(value)} characters.",
            )

    def exact_len(self, prop: str, value: str | None, length: int, message: str | None = None) -> None:
        if value is not None and len(value) != length:
            self.add(
                prop,
                message or f"'{humanize(prop)}' must be {length} characters in length. You entered {len(value)} characters.",
            )

    def email(self, prop: str, value: str | None, message: str | None = None) -> None:
        if value is None:
            return
        idx = value.find("@")
        if not (idx > 0 and idx != len(value) - 1 and idx == value.rfind("@")):
            self.add(prop, message or f"'{humanize(prop)}' is not a valid email address.")

    def greater_than(self, prop: str, value: int | None, minimum: int) -> None:
        if value is not None and not value > minimum:
            self.add(prop, f"'{humanize(prop)}' must be greater than '{minimum}'.")

    def between(self, prop: str, value: int | None, low: int, high: int) -> None:
        if value is not None and not (low <= value <= high):
            self.add(prop, f"'{humanize(prop)}' must be between {low} and {high}. You entered {value}.")

    def in_enum(self, prop: str, value, enum_cls: type[IntEnum]) -> None:
        if value is not None and value not in set(enum_cls):
            self.add(prop, f"'{humanize(prop)}' has a range of values which does not include '{value}'.")

    def strong_password(self, prop: str, value: str | None) -> None:
        """Mínimo 8 caracteres, con al menos una letra y un número."""
        v = value or ""
        if not v.strip():
            self.add(prop, "Indica la contraseña.")
        if len(v) < 8:
            self.add(prop, "La contraseña debe tener al menos 8 caracteres.")
        if len(v) > 128:
            self.add(
                prop,
                f"The length of '{humanize(prop)}' must be 128 characters or fewer. You entered {len(v)} characters.",
            )
        if not re.search("[A-Za-z]", v):
            self.add(prop, "La contraseña debe tener al menos una letra.")
        if not re.search("[0-9]", v):
            self.add(prop, "La contraseña debe tener al menos un número.")

    def for_each_max_len(self, prop: str, values: Sequence[str] | None, maximum: int) -> None:
        for i, v in enumerate(values or []):
            self.max_len(f"{prop}[{i}]", v, maximum)

    def raise_if_invalid(self) -> None:
        if self.errors:
            raise ValidationException(dict(self.errors))

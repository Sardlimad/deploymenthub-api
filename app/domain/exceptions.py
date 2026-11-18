"""Excepciones. El manejador de errores de la API las traduce a ProblemDetails con el código HTTP correcto."""


class DomainException(Exception):
    """Violación de una regla de negocio → 409 Conflict."""


class ConflictException(Exception):
    def __init__(self, message: str = "El recurso solicitado ya existe."):
        super().__init__(message)


class NotFoundException(Exception):
    def __init__(self, message: str = "El recurso solicitado no fue encontrado."):
        super().__init__(message)


class UnauthorizedException(Exception):
    """Credenciales inválidas o sesión no válida → 401."""


class ValidationException(Exception):
    def __init__(self, message_or_errors="Se produjeron errores de validación.", errors=None):
        if isinstance(message_or_errors, dict):
            super().__init__("Se produjeron errores de validación.")
            self.errors: dict[str, list[str]] = message_or_errors
        else:
            super().__init__(message_or_errors)
            self.errors = errors or {}

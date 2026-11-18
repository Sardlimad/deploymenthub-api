"""Envío de correo por SMTP.

Sin SMTP configurado, en development el correo se escribe en el log para poder probar la recuperación
de contraseña en local; fuera de development se reporta como error.
"""
import logging
import smtplib
import threading
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger("deploymenthub.email")


class EmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        """Envía y absorbe cualquier fallo: la respuesta al usuario no debe revelar si el correo existe
        o si falló el envío."""
        s = self._settings
        if not s.smtp_configured:
            if s.is_development:
                logger.warning(
                    "SMTP sin configurar (EMAIL_HOST/EMAIL_FROM). Correo NO enviado, se muestra solo en desarrollo:\n"
                    "Para: %s\nAsunto: %s\n%s", to, subject, body,
                )
            else:
                logger.error("SMTP sin configurar (EMAIL_HOST/EMAIL_FROM): no se pudo enviar el correo a %s.", to)
            return

        message = EmailMessage()
        message["From"] = s.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(s.email_host, s.email_port, timeout=20) as client:
                client.ehlo()
                if client.has_extn("starttls"):  # StartTlsWhenAvailable
                    client.starttls()
                    client.ehlo()
                if s.email_username:
                    client.login(s.email_username, s.email_password)
                client.send_message(message)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo enviar el correo a %s.", to)

    def send_in_background(self, to: str, subject: str, body: str) -> None:
        """Para correos disparados desde una petición: la respuesta no espera al SMTP."""
        threading.Thread(target=self.send, args=(to, subject, body), daemon=True, name="email-send").start()

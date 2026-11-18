"""Envío de correo por webhook HTTPS (EMAIL_WEBHOOK_URL, p. ej. Google Apps Script) o por SMTP.

Sin ninguno configurado, en development el correo se escribe en el log para poder probar la recuperación
de contraseña en local; fuera de development se reporta como error.
"""
import json
import logging
import smtplib
import threading
import urllib.request
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
        if s.webhook_configured:  # tiene prioridad: es lo que funciona donde SMTP está bloqueado
            self._send_webhook(to, subject, body)
            return
        if not s.smtp_configured:
            if s.is_development:
                logger.warning(
                    "Correo sin configurar (EMAIL_WEBHOOK_URL o EMAIL_HOST/EMAIL_FROM). Correo NO enviado, "
                    "se muestra solo en desarrollo:\nPara: %s\nAsunto: %s\n%s", to, subject, body,
                )
            else:
                logger.error("Correo sin configurar (EMAIL_WEBHOOK_URL o EMAIL_HOST/EMAIL_FROM): "
                             "no se pudo enviar el correo a %s.", to)
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

    def _send_webhook(self, to: str, subject: str, body: str) -> None:
        """POST JSON {secret, to, subject, body} al webhook. Google Apps Script responde con una redirección
        (302) hacia el resultado; urllib la sigue, y el envío ya se ejecutó en el primer POST."""
        s = self._settings
        payload = json.dumps(
            {"secret": s.email_webhook_secret, "to": to, "subject": subject, "body": body}
        ).encode("utf-8")
        request = urllib.request.Request(
            s.email_webhook_url.strip(), data=payload, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = response.read().decode("utf-8", errors="replace")
            if '"ok":true' not in result.replace(" ", "").lower():
                logger.error("El webhook de correo no confirmó el envío a %s: %s", to, result[:300])
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo enviar el correo a %s por webhook.", to)

    def send_in_background(self, to: str, subject: str, body: str) -> None:
        """Para correos disparados desde una petición: la respuesta no espera al SMTP."""
        threading.Thread(target=self.send, args=(to, subject, body), daemon=True, name="email-send").start()

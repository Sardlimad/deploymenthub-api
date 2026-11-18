"""Servicios únicos de la aplicación (correo, cola de avisos, firmador de KRUD)."""
from functools import lru_cache

from app.config import get_settings
from app.notifications.email import EmailSender
from app.notifications.queue import DeploymentEmailQueue
from app.security import KrudAssertionSigner


@lru_cache
def get_email_sender() -> EmailSender:
    return EmailSender(get_settings())


@lru_cache
def get_notification_queue() -> DeploymentEmailQueue:
    return DeploymentEmailQueue(get_settings(), get_email_sender())


@lru_cache
def get_krud_signer() -> KrudAssertionSigner:
    return KrudAssertionSigner(get_settings())

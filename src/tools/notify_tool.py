"""
Outil de notification de l'opérateur via Microsoft Graph API.

Envoie un email d'alerte à la boite de l'opérateur lorsqu'un doublon
ou une redondance est détectée par l'agent analyseur_mail.

Double canal de notification :
  1. Log journalctl (toujours, via le logger Python)
  2. Email à l'opérateur (via Graph API sendMail)
"""

import logging

import msal
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

log = logging.getLogger(__name__)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Authentification Microsoft Graph API
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    """
    Obtient un token OAuth 2.0 via le flux client credentials (MSAL).

    Returns:
        Jeton d'accès sous forme de chaîne.

    Raises:
        RuntimeError: si l'authentification échoue.
    """
    app = msal.ConfidentialClientApplication(
        client_id=settings.MS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.MS_TENANT_ID}",
        client_credential=settings.MS_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise RuntimeError(
            f"Échec auth Graph API : {result.get('error_description')}"
        )
    return result["access_token"]


# ---------------------------------------------------------------------------
# Outil CrewAI — notification opérateur
# ---------------------------------------------------------------------------

class NotifyOperatorInput(BaseModel):
    """Schéma d'entrée pour la notification de l'opérateur."""

    subject: str = Field(description="Objet de l'email de notification")
    message: str = Field(description="Corps du message de notification")


class NotifyOperatorTool(BaseTool):
    """
    Outil CrewAI pour notifier l'opérateur d'un doublon ou d'une redondance.

    Déclenche une double notification :
      1. Log WARNING dans journalctl (traçabilité permanente)
      2. Email HTML à la boite de l'opérateur (alerte proactive)

    L'email est envoyé à l'adresse MS_USER_EMAIL définie dans .env,
    c'est-à-dire la boite Outlook de l'opérateur lui-même.
    """

    name: str = "notify_operator"
    description: str = (
        "Notifie l'opérateur d'un doublon ou d'une redondance détectée. "
        "Double canal : log journalctl + email à la boite de l'opérateur. "
        "À utiliser après SheetMarkRedondanceTool ou lors d'un doublon ignoré."
    )
    args_schema: type[BaseModel] = NotifyOperatorInput

    def _run(self, subject: str, message: str) -> str:
        """
        Envoie la notification par log et par email.

        Args:
            subject: objet de l'email de notification.
            message: corps du message (texte lisible par l'opérateur).

        Returns:
            Confirmation d'envoi ou message d'erreur si l'email échoue.
        """
        # Canal 1 : log permanent dans journalctl
        log.warning(f"[MailFlow Alerte] {subject} — {message}")

        # Canal 2 : email à l'opérateur
        try:
            token = _get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            body_html = f"""
<p><strong>⚠️ Alerte MailFlow</strong></p>
<p>{message}</p>
<hr>
<p><em>Message automatique — Agent analyseur_mail MailFlow</em></p>
"""

            payload = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "HTML",
                        "content": body_html,
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": settings.MS_USER_EMAIL}}
                    ],
                },
                "saveToSentItems": "false",  # Ne pas encombrer les envoyés
            }

            url = f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}/sendMail"
            response = requests.post(
                url, headers=headers, json=payload, timeout=30
            )
            response.raise_for_status()

            return f"Notification envoyée (log + email) : {subject}"

        except Exception as exc:
            # L'échec de l'email ne bloque pas le cycle — log seul suffit
            log.error(f"Échec envoi email notification : {exc}")
            return f"Notification log OK — email échoué : {exc}"

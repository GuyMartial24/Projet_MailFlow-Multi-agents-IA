"""
Outil Microsoft Graph API — envoi d'email depuis la boite Outlook de l'utilisateur.

L'email est envoyé au format HTML pour que le lien de téléchargement du Memento
soit rendu cliquable dans tous les clients email modernes.
Aucune pièce jointe : le Memento est accessible via le lien intégré dans le corps.
"""

import msal
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

# URL de base de l'API Microsoft Graph
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Authentification Microsoft Graph API
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    """
    Obtient un token d'accès OAuth 2.0 via le flux client credentials (MSAL).

    Génère un nouveau token à chaque appel pour éviter les expirations.

    Returns:
        Jeton d'accès sous forme de chaîne.

    Raises:
        RuntimeError: si l'authentification échoue (mauvais credentials, etc.).
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
# Outil CrewAI — envoi de l'email
# ---------------------------------------------------------------------------

class SendMailInput(BaseModel):
    """Schéma d'entrée pour l'envoi d'un email via Microsoft Graph API."""

    to_email: str = Field(description="Adresse email du destinataire")
    subject: str = Field(description="Objet du mail")
    body_html: str = Field(
        description="Corps du mail en HTML avec le lien de téléchargement du Memento"
    )


class SendMailTool(BaseTool):
    """
    Outil CrewAI pour envoyer l'email avec le lien de téléchargement du Memento.

    Utilise l'endpoint sendMail de Microsoft Graph API pour envoyer l'email
    depuis la boite Outlook de l'utilisateur.

    L'email est envoyé au format HTML (contentType='HTML') pour garantir
    que le lien de téléchargement du Memento est rendu cliquable.
    L'email est automatiquement copié dans les éléments envoyés.
    """

    name: str = "send_email_via_graph"
    description: str = (
        "Envoie un email avec le lien de téléchargement du Memento depuis la boite "
        "Outlook de l'utilisateur via Microsoft Graph API. "
        "Le corps est en HTML pour que le lien soit cliquable. "
        "Aucune pièce jointe — le Memento est accessible via le lien dans le corps."
    )
    args_schema: type[BaseModel] = SendMailInput

    def _run(self, to_email: str, subject: str, body_html: str) -> str:
        """
        Envoie l'email HTML via l'endpoint sendMail de Microsoft Graph API.

        Args:
            to_email:  adresse email du destinataire.
            subject:   objet du mail (issu du Google Doc ContenuMessage).
            body_html: corps HTML du mail avec le lien de téléchargement cliquable.

        Returns:
            Message de confirmation avec l'adresse du destinataire et l'objet.

        Raises:
            requests.HTTPError: si l'API Graph retourne une erreur HTTP.
        """
        token = _get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Construction du payload Graph API sendMail
        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",  # HTML pour les liens cliquables
                    "content": body_html,
                },
                "toRecipients": [
                    {"emailAddress": {"address": to_email}}
                ],
            },
            "saveToSentItems": "true",  # Copie dans les éléments envoyés
        }

        url = f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}/sendMail"
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        return (
            f"Email avec lien de téléchargement du Memento envoyé "
            f"à {to_email} — objet : {subject}"
        )

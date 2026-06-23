"""
Outil Microsoft Graph API — envoi d'email HTML depuis la boite de l'utilisateur.

Le corps du mail est envoyé en HTML pour permettre les liens cliquables.
Pas de pièce jointe : le memento est accessible via un lien dans le corps.
"""

import msal
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_access_token() -> str:
    app = msal.ConfidentialClientApplication(
        client_id=settings.MS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.MS_TENANT_ID}",
        client_credential=settings.MS_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise RuntimeError(f"Échec auth Graph API : {result.get('error_description')}")
    return result["access_token"]


class SendMailInput(BaseModel):
    to_email:  str = Field(description="Adresse email du destinataire")
    subject:   str = Field(description="Objet du mail")
    body_html: str = Field(description="Corps du mail en HTML (liens cliquables inclus)")


class SendMailTool(BaseTool):
    name: str = "send_email_via_graph"
    description: str = (
        "Envoie un email HTML depuis la boite Outlook de l'utilisateur via Microsoft Graph API. "
        "Le corps doit être en HTML pour que le lien de téléchargement soit cliquable. "
        "Aucune pièce jointe — le memento est accessible via le lien dans le corps."
    )
    args_schema: type[BaseModel] = SendMailInput

    def _run(self, to_email: str, subject: str, body_html: str) -> str:
        token = _get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body_html,
                },
                "toRecipients": [
                    {"emailAddress": {"address": to_email}}
                ],
            },
            "saveToSentItems": "true",
        }

        url = f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}/sendMail"
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        return f"Email HTML envoyé à {to_email} — objet : {subject}"

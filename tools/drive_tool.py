"""
Outil Google Drive API.

Responsabilités :
- Exporter le Google Doc ContenuMessage en HTML et extraire objet + corps du mail
  (le corps est renvoyé en HTML pour préserver les liens cliquables)
"""

import re
import urllib.parse

from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def _export_doc_as_html(file_id: str) -> str:
    """Exporte un Google Doc natif en HTML (liens cliquables préservés)."""
    service = _get_drive_service()
    content = service.files().export_media(
        fileId=file_id,
        mimeType="text/html",
    ).execute()
    return content.decode("utf-8")


def _clean_href(href: str) -> str:
    """
    Google Docs enveloppe parfois les URLs dans google.com/url?q=...
    Cette fonction extrait l'URL réelle.
    """
    if "google.com/url" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        return qs.get("q", [href])[0]
    return href


def _rebuild_paragraph(p) -> str:
    """
    Reconstruit le contenu d'un paragraphe en HTML minimal :
    texte brut + balises <a href="..."> préservées, tout le reste aplati en texte.
    """
    parts = []
    for node in p.children:
        if getattr(node, "name", None) == "a":
            href = _clean_href(node.get("href", ""))
            text = node.get_text()
            parts.append(f'<a href="{href}">{text}</a>')
        elif hasattr(node, "get_text"):
            parts.append(node.get_text())
        else:
            parts.append(str(node))
    return "".join(parts)


def _parse_contenu_message(html: str) -> dict:
    """
    Parse l'export HTML du Google Doc ContenuMessage.
    Cherche les labels 'Objet :' et 'Corps du message :' puis extrait le contenu.
    Retourne {objet: str, corps_html: str}.
    """
    soup = BeautifulSoup(html, "html.parser")

    objet = ""
    corps_parts = []
    mode = "search_objet"

    for p in soup.find_all("p"):
        text = p.get_text()

        if mode == "search_objet":
            m = re.search(r"Objet\s*:\s*(.+)", text)
            if m:
                objet = m.group(1).strip()
                mode = "search_corps"

        elif mode == "search_corps":
            if re.search(r"Corps du message\s*:", text, re.IGNORECASE):
                mode = "collect_corps"

        elif mode == "collect_corps":
            inner = _rebuild_paragraph(p)
            if inner.strip():
                corps_parts.append(f"<p>{inner}</p>")

    corps_html = "\n".join(corps_parts)
    return {"objet": objet, "corps_html": corps_html}


# ── Tool : lecture ContenuMessage ────────────────────────────

class DriveReadMessageInput(BaseModel):
    dummy: str = Field(default="", description="Pas de paramètre requis.")


class DriveReadMessageTool(BaseTool):
    name: str = "drive_read_contenu_message"
    description: str = (
        "Exporte le Google Doc ContenuMessage depuis Google Drive en HTML et extrait "
        "l'objet du mail (label 'Objet :') et le corps HTML du mail (après 'Corps du message :'), "
        "avec le lien de téléchargement cliquable préservé. "
        "Retourne un dict {objet, corps_html}."
    )
    args_schema: type[BaseModel] = DriveReadMessageInput

    def _run(self, dummy: str = "") -> dict:
        html = _export_doc_as_html(settings.GOOGLE_DOC_CONTENU_MESSAGE_ID)
        return _parse_contenu_message(html)

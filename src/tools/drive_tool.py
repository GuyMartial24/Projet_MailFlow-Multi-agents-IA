"""
Outil Google Drive API — lecture du Google Doc ContenuMessage.

Le fichier ContenuMessage est un Google Doc natif (pas un .docx uploadé).
Il est exporté en HTML via l'API Drive pour préserver les hyperliens,
notamment le lien de téléchargement du Memento intégré dans le corps du message.

Format attendu du document :
    Objet :  Memento

    Corps du message :
    Bonjour,
    Veuillez trouver le Memento en cliquant sur ce lien : [Télécharger le Memento PDF]
    Cordialement,
"""

import re
import urllib.parse

from bs4 import BeautifulSoup
from crewai.tools import BaseTool
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from config import settings

# Scope en lecture seule : on n'écrit jamais dans Drive
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


# ---------------------------------------------------------------------------
# Client Google Drive
# ---------------------------------------------------------------------------

def _get_drive_service():
    """
    Crée et retourne un client authentifié Google Drive v3.

    Returns:
        Resource: client Google Drive prêt à l'emploi.
    """
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Export du Google Doc en HTML
# ---------------------------------------------------------------------------

def _export_doc_as_html(file_id: str) -> str:
    """
    Exporte un Google Doc natif au format HTML via l'API Drive.

    L'export HTML préserve les hyperliens (<a href="...">) contrairement
    à l'export texte brut qui les supprime.

    Args:
        file_id: identifiant Google Drive du document à exporter.

    Returns:
        Contenu HTML du document sous forme de chaîne UTF-8.
    """
    service = _get_drive_service()
    content = service.files().export_media(
        fileId=file_id,
        mimeType="text/html",
    ).execute()
    return content.decode("utf-8")


# ---------------------------------------------------------------------------
# Nettoyage des URLs Google (désenveloppement)
# ---------------------------------------------------------------------------

def _clean_href(href: str) -> str:
    """
    Extrait l'URL réelle depuis un lien Google de redirection.

    Google Docs enveloppe parfois les URLs sous la forme :
        https://www.google.com/url?q=https://drive.google.com/...&sa=D&...

    Cette fonction retourne directement la valeur du paramètre 'q'.

    Args:
        href: URL brute extraite de l'attribut href d'une balise <a>.

    Returns:
        URL cible réelle, ou href inchangé si ce n'est pas un lien Google.
    """
    if "google.com/url" in href:
        query_string = urllib.parse.parse_qs(
            urllib.parse.urlparse(href).query
        )
        return query_string.get("q", [href])[0]
    return href


# ---------------------------------------------------------------------------
# Reconstruction d'un paragraphe en HTML minimal
# ---------------------------------------------------------------------------

def _rebuild_paragraph(paragraph) -> str:
    """
    Reconstruit le contenu d'un paragraphe HTML en ne conservant que les balises <a>.

    Tous les autres éléments HTML (span, strong, em, etc.) sont aplatis en texte
    brut pour produire un HTML minimal compatible email.

    Args:
        paragraph: objet Tag BeautifulSoup représentant un paragraphe <p>.

    Returns:
        Chaîne HTML contenant le texte brut et les balises <a href="..."> préservées.
    """
    parts = []
    for node in paragraph.children:
        if getattr(node, "name", None) == "a":
            # Balise <a> : préserver le lien avec l'URL désenveloppée
            href = _clean_href(node.get("href", ""))
            text = node.get_text()
            parts.append(f'<a href="{href}">{text}</a>')
        elif hasattr(node, "get_text"):
            # Autres balises HTML : aplaties en texte brut
            parts.append(node.get_text())
        else:
            # Nœud texte brut (NavigableString)
            parts.append(str(node))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Parsing du Google Doc ContenuMessage
# ---------------------------------------------------------------------------

def _parse_contenu_message(html: str) -> dict:
    """
    Parse l'export HTML du Google Doc ContenuMessage et extrait l'objet et le corps.

    Algorithme de parsing séquentiel à trois états :
      1. 'search_objet'  : cherche la ligne contenant 'Objet :' → extrait la valeur
      2. 'search_corps'  : cherche la ligne 'Corps du message :' → change d'état
      3. 'collect_corps' : collecte tous les paragraphes suivants en HTML minimal

    Args:
        html: contenu HTML brut exporté depuis Google Drive.

    Returns:
        Dict avec les clés :
          - 'objet'     (str) : objet de l'email à envoyer
          - 'corps_html' (str) : corps HTML de l'email avec liens préservés
    """
    soup = BeautifulSoup(html, "html.parser")

    objet = ""
    corps_parts = []
    mode = "search_objet"  # États : search_objet → search_corps → collect_corps

    for paragraph in soup.find_all("p"):
        text = paragraph.get_text()

        if mode == "search_objet":
            match = re.search(r"Objet\s*:\s*(.+)", text)
            if match:
                objet = match.group(1).strip()
                mode = "search_corps"

        elif mode == "search_corps":
            if re.search(r"Corps du message\s*:", text, re.IGNORECASE):
                mode = "collect_corps"

        elif mode == "collect_corps":
            # Reconstruction du paragraphe en HTML minimal (liens préservés)
            inner = _rebuild_paragraph(paragraph)
            if inner.strip():
                corps_parts.append(f"<p>{inner}</p>")

    corps_html = "\n".join(corps_parts)
    return {"objet": objet, "corps_html": corps_html}


# ---------------------------------------------------------------------------
# Outil CrewAI — lecture du ContenuMessage
# ---------------------------------------------------------------------------

class DriveReadMessageInput(BaseModel):
    """Schéma d'entrée du tool (aucun paramètre requis)."""

    dummy: str = Field(default="", description="Pas de paramètre requis.")


class DriveReadMessageTool(BaseTool):
    """
    Outil CrewAI pour lire le contenu de l'email depuis Google Drive.

    Exporte le Google Doc ContenuMessage en HTML et en extrait :
      - L'objet du mail (ligne 'Objet :')
      - Le corps HTML du mail (section 'Corps du message :')
        avec le lien de téléchargement du Memento cliquable préservé.
    """

    name: str = "drive_read_contenu_message"
    description: str = (
        "Exporte le Google Doc ContenuMessage depuis Google Drive en HTML et extrait "
        "l'objet du mail (label 'Objet :') et le corps HTML du mail "
        "(section 'Corps du message :'), avec le lien de téléchargement du Memento "
        "cliquable préservé. Retourne un dict {objet, corps_html}."
    )
    args_schema: type[BaseModel] = DriveReadMessageInput

    def _run(self, dummy: str = "") -> dict:
        """
        Exporte et parse le Google Doc ContenuMessage.

        Args:
            dummy: paramètre inutilisé (requis par l'interface BaseTool).

        Returns:
            Dict {objet: str, corps_html: str}.
        """
        html = _export_doc_as_html(settings.GOOGLE_DOC_CONTENU_MESSAGE_ID)
        return _parse_contenu_message(html)

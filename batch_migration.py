"""
Script de migration one-shot — MailFlow.

Importe tous les emails du dossier Outlook
"demande de telechargement memento" vers le Google Sheet.

Execution (une seule fois sur le VPS) :
    cd /home/ubuntu/Projets_en_Production/MailFlow
    source .venv/bin/activate
    python batch_migration.py

Le script est independant des agents en production :
il peut tourner pendant que le service mailflow est actif.
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import msal
import requests

from config import settings
from tools.outlook_tool import _extract_from_wordpress_body
from tools.sheets_tool import SheetFindEmailTool, SheetAppendTool

# Nom exact du dossier Outlook (insensible a la casse)
FOLDER_NAME = "demande de telechargement memento"

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
PAGE_SIZE = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s - %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger(__name__)


def _get_token() -> str:
    """Obtient un token OAuth 2.0 via MSAL."""
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
            f"Echec authentification : {result.get('error_description')}"
        )
    return result["access_token"]


def _find_folder(token: str, name: str) -> str | None:
    """Recherche l'ID du dossier Outlook par nom (insensible a la casse, recursif)."""
    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}/mailFolders"
        f"?$top=100&includeHiddenFolders=true"
    )
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for folder in data.get("value", []):
            if folder["displayName"].strip().lower() == name.strip().lower():
                return folder["id"]
            if folder.get("childFolderCount", 0) > 0:
                child_id = _find_in_children(token, folder["id"], name, headers)
                if child_id:
                    return child_id
        url = data.get("@odata.nextLink")
    return None


def _find_in_children(
    token: str, parent_id: str, name: str, headers: dict
) -> str | None:
    """Recherche recursive dans les sous-dossiers."""
    url = (
        f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}"
        f"/mailFolders/{parent_id}/childFolders?$top=100"
    )
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for folder in data.get("value", []):
            if folder["displayName"].strip().lower() == name.strip().lower():
                return folder["id"]
            if folder.get("childFolderCount", 0) > 0:
                child_id = _find_in_children(token, folder["id"], name, headers)
                if child_id:
                    return child_id
        url = data.get("@odata.nextLink")
    return None


def _fetch_all_messages(token: str, folder_id: str) -> list[dict]:
    """Recupere tous les emails d'un dossier avec pagination automatique."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.body-content-type="text"',
    }
    url = (
        f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}"
        f"/mailFolders/{folder_id}/messages"
        f"?$select=subject,body,receivedDateTime&$top={PAGE_SIZE}"
    )
    messages = []
    page = 1
    while url:
        log.info(f"Page {page} - {len(messages)} emails recuperes...")
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        messages.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        page += 1
    return messages


def main() -> None:
    log.info("=" * 60)
    log.info(f"BATCH MIGRATION - Dossier : '{FOLDER_NAME}'")
    log.info("=" * 60)

    token = _get_token()
    log.info("Authentification Microsoft Graph API OK")

    log.info(f"Recherche du dossier '{FOLDER_NAME}'...")
    folder_id = _find_folder(token, FOLDER_NAME)
    if not folder_id:
        log.error(
            f"Dossier '{FOLDER_NAME}' introuvable. "
            f"Verifiez la variable FOLDER_NAME (ligne 32)."
        )
        return
    log.info("Dossier trouve")

    messages = _fetch_all_messages(token, folder_id)
    total = len(messages)
    log.info(f"{total} emails trouves dans le dossier")

    if total == 0:
        log.info("Aucun email a traiter. Fin du script.")
        return

    find_tool = SheetFindEmailTool()
    append_tool = SheetAppendTool()

    inserted = skipped = unparsable = errors = 0

    for i, msg in enumerate(messages, 1):
        body = msg.get("body", {}).get("content", "")
        email, prenom, nom = _extract_from_wordpress_body(body)

        if not email:
            log.warning(
                f"[{i:3}/{total}] Non parsable - {msg.get('subject', '')[:60]}"
            )
            unparsable += 1
            continue

        try:
            result = find_tool._run(email=email)
            if result.get("found"):
                log.info(
                    f"[{i:3}/{total}] Doublon ignore - {email} "
                    f"(ligne {result.get('row_index')}, statut={result.get('statut')})"
                )
                skipped += 1
                continue

            res = append_tool._run(email=email, prenom=prenom, nom=nom)
            log.info(f"[{i:3}/{total}] INSERE - {res}")
            inserted += 1

        except Exception as exc:
            log.error(f"[{i:3}/{total}] Erreur sur {email} : {exc}")
            errors += 1

    log.info("")
    log.info("=" * 60)
    log.info("BILAN MIGRATION")
    log.info(f"  Total emails dans le dossier     : {total}")
    log.info(f"  Inseres dans le Google Sheet     : {inserted}")
    log.info(f"  Doublons ignores                 : {skipped}")
    log.info(f"  Non parsables (ligne De: absente): {unparsable}")
    log.info(f"  Erreurs                          : {errors}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()

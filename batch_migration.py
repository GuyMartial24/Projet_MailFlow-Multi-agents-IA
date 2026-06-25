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

import time

import msal
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings
from tools.outlook_tool import _extract_from_wordpress_body
from tools.sheets_tool import TOTAL_COLUMNS, _col_letter, _extract_company

# Nom exact du dossier Outlook (insensible a la casse)
FOLDER_NAME = "demandes téléchargements mémento 2025"

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

    # ── Connexion Google Sheets ──────────────────────────────────────────────
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheets = build("sheets", "v4", credentials=creds)

    # ── Lecture unique du Sheet (1 seul appel API) ───────────────────────────
    log.info("Lecture du Google Sheet (1 seul appel)...")
    result = sheets.spreadsheets().values().get(
        spreadsheetId=settings.GOOGLE_SHEET_ID,
        range=f"{settings.GOOGLE_SHEET_TAB}!A:Q",
    ).execute()
    existing_rows = result.get("values", [])

    # Ensemble des emails déjà présents (colonne E = index 4), en minuscules
    existing_emails = set()
    for idx, row in enumerate(existing_rows):
        if idx == 0:  # ignorer l'en-tête
            continue
        if len(row) > settings.COL_EMAIL and row[settings.COL_EMAIL].strip():
            existing_emails.add(row[settings.COL_EMAIL].strip().lower())

    # Prochaine ligne vide basée sur la colonne A
    next_row = len(existing_rows) + 1
    log.info(f"{len(existing_emails)} emails existants | prochaine ligne : {next_row}")

    col_end = _col_letter(TOTAL_COLUMNS - 1)  # 'Q'
    year = str(__import__("datetime").datetime.now().year)

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

        # Vérification doublon en mémoire (0 appel API)
        if email.strip().lower() in existing_emails:
            log.info(f"[{i:3}/{total}] Doublon ignore - {email}")
            skipped += 1
            continue

        try:
            from datetime import datetime as _dt
            now = _dt.now().strftime("%d/%m/%Y %H:%M")

            prenom_fmt = prenom.title()
            nom_fmt = nom.upper()
            contact = f"{prenom_fmt} {nom_fmt}"
            societe = _extract_company(email)

            row = [""] * TOTAL_COLUMNS
            row[settings.COL_DEVIS] = year
            row[settings.COL_SOCIETE] = societe
            row[settings.COL_CONTACT] = contact
            row[settings.COL_EMAIL] = email
            row[settings.COL_STATUT] = settings.STATUT_EN_ATTENTE
            row[settings.COL_DATE_PREMIERE] = now

            target = f"{settings.GOOGLE_SHEET_TAB}!A{next_row}:{col_end}{next_row}"
            sheets.spreadsheets().values().update(
                spreadsheetId=settings.GOOGLE_SHEET_ID,
                range=target,
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            ).execute()

            existing_emails.add(email.strip().lower())  # anti-doublon in-session
            next_row += 1
            inserted += 1
            log.info(
                f"[{i:3}/{total}] INSERE - {contact} <{email}> | "
                f"Societe : {societe} | {now}"
            )
            time.sleep(1.1)  # respecte la limite de 60 ecritures/min

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

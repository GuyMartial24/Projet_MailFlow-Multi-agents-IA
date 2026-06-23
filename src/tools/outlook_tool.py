"""
Outil Microsoft Graph API — lecture boite Outlook.

Structure réelle des emails WordPress reçus :
  En-tête  → De : Formulaire <formulaire@exemple.fr>  (filtre d'entrée uniquement)
  Corps    → "De : Jean Dupont jean.dupont@gmail.com"  (source unique d'extraction)

L'email, le prénom et le NOM du vrai demandeur sont extraits
exclusivement depuis la ligne "De :" dans le corps du message.
"""

import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import msal
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

STATE_FILE = Path("state/last_check_outlook.json")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ── Auth ─────────────────────────────────────────────────────

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


# ── Persistence timestamp ─────────────────────────────────────

def _load_last_check() -> Optional[str]:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("last_check")
    return None


def _save_last_check(ts: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_check": ts}, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Extraction depuis le corps du formulaire WordPress ────────

def _extract_from_wordpress_body(body: str) -> tuple[str, str, str]:
    """
    Extrait email, prénom et NOM depuis la ligne "De :" du corps WordPress.

    Format attendu dans le corps :
        De : Jean Dupont jean.dupont@gmail.com

    Retourne (email, prenom, nom) ou ("", "", "") si non trouvé.
    """
    # Regex : "De :" suivi du nom complet puis de l'email
    pattern = re.compile(
        r"De\s*:\s*(.+?)\s+([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})",
        re.IGNORECASE,
    )
    m = pattern.search(body)
    if not m:
        return "", "", ""

    full_name = m.group(1).strip()
    email     = m.group(2).strip()

    parts  = full_name.split()
    prenom = parts[0] if parts else ""
    nom    = " ".join(parts[1:]) if len(parts) > 1 else ""

    return email, prenom, nom


# ── Filtre objet ──────────────────────────────────────────────

def _subject_matches(subject: str) -> bool:
    s = subject.lower()
    return any(kw in s for kw in settings.SUBJECT_KEYWORDS)


# ── Tool CrewAI ───────────────────────────────────────────────

class OutlookFetchInput(BaseModel):
    dummy: str = Field(default="", description="Pas de paramètre requis.")


class OutlookFetchTool(BaseTool):
    name: str = "outlook_fetch_new_emails"
    description: str = (
        "Récupère les nouveaux emails de formulaire@exemple.fr dans la boite Outlook "
        "depuis la dernière exécution, filtrés par mots-clés dans l'objet. "
        "Extrait l'email, le prénom et le NOM du vrai demandeur depuis la ligne "
        "'De :' dans le corps du formulaire WordPress. "
        "Retourne une liste de dicts {email, prenom, nom, received_at}."
    )
    args_schema: type[BaseModel] = OutlookFetchInput

    def _run(self, dummy: str = "") -> list[dict]:
        token = _get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            # Demande le corps en texte brut pour simplifier le parsing
            "Prefer": 'outlook.body-content-type="text"',
        }

        last_check = _load_last_check()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        filter_parts = [
            f"from/emailAddress/address eq '{settings.FILTER_SENDER}'"
        ]
        if last_check:
            filter_parts.append(f"receivedDateTime gt {last_check}")

        odata_filter = " and ".join(filter_parts)

        url = (
            f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}/messages"
            f"?$filter={odata_filter}"
            f"&$select=subject,body,receivedDateTime"
            f"&$top=50"
            f"&$orderby=receivedDateTime asc"
        )

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        messages = response.json().get("value", [])

        results = []
        for msg in messages:
            subject = msg.get("subject", "")
            if not _subject_matches(subject):
                continue

            body_content = msg.get("body", {}).get("content", "")
            email, prenom, nom = _extract_from_wordpress_body(body_content)

            if not email:
                continue  # corps non parsable, on ignore

            results.append({
                "email":       email,
                "prenom":      prenom,
                "nom":         nom,
                "received_at": msg.get("receivedDateTime", ""),
            })

        _save_last_check(now_iso)
        return results

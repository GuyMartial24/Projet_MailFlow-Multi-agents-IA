"""
Outil Microsoft Graph API — lecture boite Outlook de l'utilisateur.

Responsabilités :
- Authentification OAuth 2.0 (client credentials flow)
- Récupération des emails depuis la dernière connexion
- Filtrage : expéditeur ET mots-clés objet
- Extraction Prénom/NOM depuis le corps du formulaire ET le champ From
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

# ── Fichier de persistence du dernier timestamp de lecture ──
STATE_FILE = Path("state/last_check_outlook.json")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ── Auth ────────────────────────────────────────────────────

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


# ── Persistence timestamp ────────────────────────────────────

def _load_last_check() -> Optional[str]:
    """Retourne le timestamp ISO 8601 de la dernière vérification, ou None."""
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


# ── Extraction nom/prénom ────────────────────────────────────

def _extract_from_body(body: str) -> tuple[str, str]:
    """
    Tente d'extraire Prénom et NOM depuis le corps d'un formulaire WordPress.
    Retourne ("", "") si non trouvé.
    """
    prenom = ""
    nom = ""

    patterns_prenom = [
        r"[Pp]r[eé]nom\s*[:\-]\s*([^\n\r<]+)",
        r"[Ff]irst\s*[Nn]ame\s*[:\-]\s*([^\n\r<]+)",
    ]
    patterns_nom = [
        r"(?<![Pp]r[eé])(?:^|[\s\n])(?:NOM|[Nn]om)\s*[:\-]\s*([^\n\r<]+)",
        r"[Ll]ast\s*[Nn]ame\s*[:\-]\s*([^\n\r<]+)",
    ]

    for p in patterns_prenom:
        m = re.search(p, body)
        if m:
            prenom = m.group(1).strip()
            break

    for p in patterns_nom:
        m = re.search(p, body)
        if m:
            nom = m.group(1).strip()
            break

    return prenom, nom


def _extract_from_address(display_name: str) -> tuple[str, str]:
    """
    Tente de décomposer 'Prénom NOM' depuis le display name de l'expéditeur.
    Retourne ("", "") si impossible.
    """
    parts = display_name.strip().split()
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) > 2:
        return parts[0], " ".join(parts[1:])
    return display_name, ""


def _pick_most_complete(
    body_prenom: str, body_nom: str,
    from_prenom: str, from_nom: str,
) -> tuple[str, str]:
    """Conserve la version la plus complète pour chaque champ."""
    prenom = body_prenom if len(body_prenom) >= len(from_prenom) else from_prenom
    nom    = body_nom    if len(body_nom)    >= len(from_nom)    else from_nom
    return prenom, nom


# ── Filtre objet ─────────────────────────────────────────────

def _subject_matches(subject: str) -> bool:
    s = subject.lower()
    return any(kw in s for kw in settings.SUBJECT_KEYWORDS)


# ── Tool CrewAI ──────────────────────────────────────────────

class OutlookFetchInput(BaseModel):
    dummy: str = Field(default="", description="Pas de paramètre requis.")


class OutlookFetchTool(BaseTool):
    name: str = "outlook_fetch_new_emails"
    description: str = (
        "Récupère les nouveaux emails entrants dans la boite Outlook de l'utilisateur "
        "depuis la dernière exécution. Filtre sur l'expéditeur formulaire@exemple.fr "
        "ET des mots-clés dans l'objet liés aux demandes de memento. "
        "Retourne une liste de dicts {email, prenom, nom, received_at}."
    )
    args_schema: type[BaseModel] = OutlookFetchInput

    def _run(self, dummy: str = "") -> list[dict]:
        token = _get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        last_check = _load_last_check()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Filtre OData : expéditeur ET date > dernière vérification
        filter_parts = [
            f"from/emailAddress/address eq '{settings.FILTER_SENDER}'"
        ]
        if last_check:
            filter_parts.append(f"receivedDateTime gt {last_check}")

        odata_filter = " and ".join(filter_parts)

        url = (
            f"{GRAPH_BASE}/users/{settings.MS_USER_EMAIL}/messages"
            f"?$filter={odata_filter}"
            f"&$select=subject,from,body,receivedDateTime"
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

            sender_email   = msg["from"]["emailAddress"]["address"]
            sender_display = msg["from"]["emailAddress"].get("name", "")
            body_content   = msg.get("body", {}).get("content", "")

            body_prenom, body_nom   = _extract_from_body(body_content)
            from_prenom, from_nom   = _extract_from_address(sender_display)
            prenom, nom = _pick_most_complete(body_prenom, body_nom, from_prenom, from_nom)

            results.append({
                "email":       sender_email,
                "prenom":      prenom,
                "nom":         nom,
                "received_at": msg.get("receivedDateTime", ""),
            })

        _save_last_check(now_iso)
        return results

"""
Outil Microsoft Graph API â€” lecture de la boite Outlook.

Structure rÃ©elle des emails WordPress reÃ§us :
  En-tÃªte : De : Formulaire <formulaire@exemple.fr>  â†’ filtre d'entrÃ©e uniquement
  Corps   : "De : Jean Dupont jean.dupont@gmail.com"  â†’ source unique d'extraction

Le champ From de l'email est toujours 'Formulaire' (expÃ©diteur WordPress),
jamais le vrai demandeur. Toute l'extraction (email, prÃ©nom, NOM) se fait
exclusivement depuis la ligne "De :" dans le corps du message.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import msal
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

# Fichier local stockant le timestamp de la derniÃ¨re vÃ©rification (fetch incrÃ©mental)
STATE_FILE = Path("state/last_check_outlook.json")

# URL de base de l'API Microsoft Graph
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Authentification Microsoft Graph API
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    """
    Obtient un token d'accÃ¨s OAuth 2.0 via le flux client credentials (MSAL).

    Le token est gÃ©nÃ©rÃ© Ã  la demande Ã  chaque cycle et n'est pas mis en cache
    pour Ã©viter les expirations silencieuses.

    Returns:
        Jeton d'accÃ¨s sous forme de chaÃ®ne.

    Raises:
        RuntimeError: si l'authentification Ã©choue (mauvais credentials, etc.).
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
            f"Ã‰chec auth Graph API : {result.get('error_description')}"
        )
    return result["access_token"]


# ---------------------------------------------------------------------------
# Gestion du timestamp de dernier fetch (fetch incrÃ©mental)
# ---------------------------------------------------------------------------

def _load_last_check() -> Optional[str]:
    """
    Lit le timestamp ISO 8601 de la derniÃ¨re vÃ©rification depuis le fichier d'Ã©tat.

    Returns:
        Timestamp sous forme de chaÃ®ne (ex: '2026-06-23T10:00:00Z'),
        ou None si le fichier n'existe pas encore (premier dÃ©marrage).
    """
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("last_check")
    return None


def _save_last_check(ts: str) -> None:
    """
    Sauvegarde le timestamp ISO 8601 du cycle en cours dans le fichier d'Ã©tat.

    CrÃ©e le rÃ©pertoire state/ si nÃ©cessaire.

    Args:
        ts: timestamp ISO 8601 Ã  persister (ex: '2026-06-23T10:05:00Z').
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_check": ts}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Extraction du nom depuis l'adresse email (source secondaire)
# ---------------------------------------------------------------------------

# Parties locales generiques a ignorer
_GENERIC_LOCALS = {
    "contact", "info", "admin", "support", "noreply", "no-reply",
    "hello", "bonjour", "service", "direction", "secretariat",
    "accueil", "communication", "commercial", "rdv",
}


def _extract_name_from_email(email: str) -> tuple[str, str]:
    """
    Tente d'extraire prenom et nom depuis la partie locale de l'adresse email.

    Exemples :
      paul.martin@entreprise.com      -> ("Paul", "Martin")
      marie-claire.durand@exemple.fr     -> ("Marie-Claire", "Durand")
      p.martin@entreprise.com          -> ("", "")   # initiale seule = ignoree
      jdupont75@gmail.com         -> ("", "")   # chiffres = ignore
      contact@company.com         -> ("", "")   # generique = ignore

    Returns:
        Tuple (prenom_raw, nom_raw) sans formatage de casse.
        Retourne ("", "") si l'extraction n'est pas fiable.
    """
    try:
        local = email.split("@")[0].lower()
    except IndexError:
        return "", ""

    # Ignorer les adresses generiques
    if local in _GENERIC_LOCALS:
        return "", ""

    # Ignorer si commence par un chiffre (alias numerique type jdupont75)
    if local and local[0].isdigit():
        return "", ""

    # Decouper par separateurs courants : point, tiret, underscore
    raw_parts = re.split(r"[.\-_]", local)

    # Filtrer : garder uniquement les parties sans chiffres et de longueur > 1
    # (les initialesseules comme "c" sont peu fiables)
    meaningful = [
        p for p in raw_parts
        if len(p) > 1 and not any(c.isdigit() for c in p)
    ]

    if not meaningful:
        return "", ""
    if len(meaningful) == 1:
        # Un seul mot : prenom seulement, nom vide
        return meaningful[0], ""

    # Plusieurs mots : premier = prenom, reste = nom
    prenom_raw = meaningful[0]
    nom_raw = " ".join(meaningful[1:])
    return prenom_raw, nom_raw


def _pick_best_name(
    body_prenom: str,
    body_nom: str,
    email_prenom: str,
    email_nom: str,
) -> tuple[str, str]:
    """
    Compare les deux sources et retient la version la plus complete.

    Regles de priorite :
      1. Si une source a prenom ET nom, l'autre seulement prenom -> prefer complete
      2. Si les deux ont prenom+nom -> prefer body (saisie directe, plus authentique)
      3. Si email n'apporte rien -> garder body tel quel

    La mise en forme (title case / uppercase) est appliquee par l'appelant.

    Returns:
        Tuple (prenom_raw, nom_raw) sans formatage de casse.
    """
    body_score = (1 if body_prenom else 0) + (1 if body_nom else 0)
    email_score = (1 if email_prenom else 0) + (1 if email_nom else 0)

    if email_score > body_score:
        # Email apporte plus d'information (ex : body="Martin"+"", email="Paul"+"Martin")
        return email_prenom, email_nom

    # Par defaut : body (plus authentique quand equivalent ou superieur)
    return body_prenom, body_nom


# ---------------------------------------------------------------------------
# Extraction des donnees du demandeur depuis le corps du formulaire
# ---------------------------------------------------------------------------

def _extract_from_wordpress_body(body: str) -> tuple[str, str, str]:
    """
    Extrait l'email, le prÃ©nom et le NOM du demandeur depuis le corps du mail WordPress.

    Le formulaire de contact WordPress gÃ©nÃ¨re un email dont le corps contient :
        De : Jean Dupont jean.dupont@gmail.com
        Objet : Demande MÃ©mento 2025
        Corps du message : ...

    La regex cible la ligne 'De :' et sÃ©pare le nom complet de l'adresse email.

    Args:
        body: contenu texte brut du corps de l'email.

    Returns:
        Tuple (email, prenom, nom). Retourne ("", "", "") si la ligne est absente
        ou ne correspond pas au format attendu.
    """
        # Capture : tout ce qui precede l'email = nom complet, puis l'email lui-meme
    pattern = re.compile(
        r"De\s*:\s*(.+?)\s+([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})",
        re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return "", "", ""

    full_name = match.group(1).strip()
    email = match.group(2).strip()

    # Source 1 : decomposition du nom complet depuis le corps du formulaire
    parts = full_name.split()
    body_prenom = parts[0] if parts else ""
    body_nom = " ".join(parts[1:]) if len(parts) > 1 else ""

    # Source 2 : extraction depuis la partie locale de l'adresse email
    email_prenom, email_nom = _extract_name_from_email(email)

    # Comparaison : on retient la version la plus complete
    prenom, nom = _pick_best_name(body_prenom, body_nom, email_prenom, email_nom)

    return email, prenom, nom


# ---------------------------------------------------------------------------
# Filtre sur l'objet de l'email
# ---------------------------------------------------------------------------

def _subject_matches(subject: str) -> bool:
    """
    VÃ©rifie si l'objet de l'email correspond Ã  une demande de Memento.

    Compare l'objet (en minuscules) avec chaque mot-clÃ© dÃ©fini dans
    settings.SUBJECT_KEYWORDS (condition OR).

    Args:
        subject: objet de l'email Ã  vÃ©rifier.

    Returns:
        True si l'objet contient au moins un des mots-clÃ©s, False sinon.
    """
    subject_lower = subject.lower()
    return any(kw in subject_lower for kw in settings.SUBJECT_KEYWORDS)


# ---------------------------------------------------------------------------
# Outil CrewAI â€” fetch des nouveaux emails
# ---------------------------------------------------------------------------

class OutlookFetchInput(BaseModel):
    """SchÃ©ma d'entrÃ©e du tool (aucun paramÃ¨tre requis)."""

    dummy: str = Field(default="", description="Pas de paramÃ¨tre requis.")


class OutlookFetchTool(BaseTool):
    """
    Outil CrewAI pour rÃ©cupÃ©rer les nouveaux emails de demande de Memento.

    Interroge la boite Outlook via Microsoft Graph API en mode incrÃ©mental :
    seuls les emails reÃ§us depuis le dernier cycle sont rÃ©cupÃ©rÃ©s.
    """

    name: str = "outlook_fetch_new_emails"
    description: str = (
        "RÃ©cupÃ¨re les nouveaux emails de formulaire@exemple.fr dans la boite Outlook "
        "depuis la derniÃ¨re exÃ©cution, filtrÃ©s par mots-clÃ©s dans l'objet. "
        "Extrait l'email, le prÃ©nom et le NOM du vrai demandeur depuis la ligne "
        "'De :' dans le corps du formulaire WordPress. "
        "Retourne une liste de dicts {email, prenom, nom, received_at}."
    )
    args_schema: type[BaseModel] = OutlookFetchInput

    def _run(self, dummy: str = "") -> list[dict]:
        """
        ExÃ©cute le fetch incrÃ©mental et retourne les demandes dÃ©tectÃ©es.

        Ã‰tapes :
          1. Authentification Graph API
          2. Construction du filtre OData (expÃ©diteur + date > last_check)
          3. RÃ©cupÃ©ration des messages en texte brut
          4. Filtrage par objet et extraction du demandeur depuis le corps
          5. Sauvegarde du timestamp courant

        Args:
            dummy: paramÃ¨tre inutilisÃ© (requis par l'interface BaseTool).

        Returns:
            Liste de dicts {email, prenom, nom, received_at}.
            Liste vide si aucun email ne correspond aux filtres.
        """
        token = _get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            # Demande le corps en texte brut pour simplifier le parsing
            "Prefer": 'outlook.body-content-type="text"',
        }

        last_check = _load_last_check()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Filtre OData : expÃ©diteur WordPress ET date supÃ©rieure au dernier cycle
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
        )

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        messages = response.json().get("value", [])
        messages.sort(key=lambda m: m.get("receivedDateTime", ""))

        results = []
        for msg in messages:
            subject = msg.get("subject", "")

            # Second filtre : vÃ©rification des mots-clÃ©s dans l'objet
            if not _subject_matches(subject):
                continue

            body_content = msg.get("body", {}).get("content", "")
            email, prenom, nom = _extract_from_wordpress_body(body_content)

            # Corps non parsable ou ligne "De :" absente : email ignorÃ©
            if not email:
                continue

            results.append({
                "email": email,
                "prenom": prenom,
                "nom": nom,
                "received_at": msg.get("receivedDateTime", ""),
            })

        # Mise Ã  jour du timestamp aprÃ¨s traitement pour le prochain cycle
        _save_last_check(now_iso)
        return results

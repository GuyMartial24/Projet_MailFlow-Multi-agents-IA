"""
Outil Microsoft Graph API — lecture de la boite Outlook.

Structure réelle des emails WordPress reçus :
  En-tête : De : Formulaire <formulaire@exemple.fr>  → filtre d'entrée uniquement
  Corps   : "De : Jean Dupont jean.dupont@gmail.com"  → source unique d'extraction

Le champ From de l'email est toujours 'Formulaire' (expéditeur WordPress),
jamais le vrai demandeur. Toute l'extraction (email, prénom, NOM) se fait
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

# Fichier local stockant le timestamp de la dernière vérification (fetch incrémental)
STATE_FILE = Path("state/last_check_outlook.json")

# URL de base de l'API Microsoft Graph
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Authentification Microsoft Graph API
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    """
    Obtient un token d'accès OAuth 2.0 via le flux client credentials (MSAL).

    Le token est généré à la demande à chaque cycle et n'est pas mis en cache
    pour éviter les expirations silencieuses.

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
# Gestion du timestamp de dernier fetch (fetch incrémental)
# ---------------------------------------------------------------------------

def _load_last_check() -> Optional[str]:
    """
    Lit le timestamp ISO 8601 de la dernière vérification depuis le fichier d'état.

    Returns:
        Timestamp sous forme de chaîne (ex: '2026-06-23T10:00:00Z'),
        ou None si le fichier n'existe pas encore (premier démarrage).
    """
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("last_check")
    return None


def _save_last_check(ts: str) -> None:
    """
    Sauvegarde le timestamp ISO 8601 du cycle en cours dans le fichier d'état.

    Crée le répertoire state/ si nécessaire.

    Args:
        ts: timestamp ISO 8601 à persister (ex: '2026-06-23T10:05:00Z').
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_check": ts}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Extraction des données du demandeur depuis le corps du formulaire
# ---------------------------------------------------------------------------

def _extract_from_wordpress_body(body: str) -> tuple[str, str, str]:
    """
    Extrait l'email, le prénom et le NOM du demandeur depuis le corps du mail WordPress.

    Le formulaire de contact WordPress génère un email dont le corps contient :
        De : Jean Dupont jean.dupont@gmail.com
        Objet : Demande Mémento 2025
        Corps du message : ...

    La regex cible la ligne 'De :' et sépare le nom complet de l'adresse email.

    Args:
        body: contenu texte brut du corps de l'email.

    Returns:
        Tuple (email, prenom, nom). Retourne ("", "", "") si la ligne est absente
        ou ne correspond pas au format attendu.
    """
    # Capture : tout ce qui précède l'email = nom complet, puis l'email lui-même
    pattern = re.compile(
        r"De\s*:\s*(.+?)\s+([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})",
        re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return "", "", ""

    full_name = match.group(1).strip()
    email = match.group(2).strip()

    # Décomposition du nom complet : premier mot = prénom, reste = NOM
    parts = full_name.split()
    prenom = parts[0] if parts else ""
    nom = " ".join(parts[1:]) if len(parts) > 1 else ""

    return email, prenom, nom


# ---------------------------------------------------------------------------
# Filtre sur l'objet de l'email
# ---------------------------------------------------------------------------

def _subject_matches(subject: str) -> bool:
    """
    Vérifie si l'objet de l'email correspond à une demande de Memento.

    Compare l'objet (en minuscules) avec chaque mot-clé défini dans
    settings.SUBJECT_KEYWORDS (condition OR).

    Args:
        subject: objet de l'email à vérifier.

    Returns:
        True si l'objet contient au moins un des mots-clés, False sinon.
    """
    subject_lower = subject.lower()
    return any(kw in subject_lower for kw in settings.SUBJECT_KEYWORDS)


# ---------------------------------------------------------------------------
# Outil CrewAI — fetch des nouveaux emails
# ---------------------------------------------------------------------------

class OutlookFetchInput(BaseModel):
    """Schéma d'entrée du tool (aucun paramètre requis)."""

    dummy: str = Field(default="", description="Pas de paramètre requis.")


class OutlookFetchTool(BaseTool):
    """
    Outil CrewAI pour récupérer les nouveaux emails de demande de Memento.

    Interroge la boite Outlook via Microsoft Graph API en mode incrémental :
    seuls les emails reçus depuis le dernier cycle sont récupérés.
    """

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
        """
        Exécute le fetch incrémental et retourne les demandes détectées.

        Étapes :
          1. Authentification Graph API
          2. Construction du filtre OData (expéditeur + date > last_check)
          3. Récupération des messages en texte brut
          4. Filtrage par objet et extraction du demandeur depuis le corps
          5. Sauvegarde du timestamp courant

        Args:
            dummy: paramètre inutilisé (requis par l'interface BaseTool).

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

        # Filtre OData : expéditeur WordPress ET date supérieure au dernier cycle
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

            # Second filtre : vérification des mots-clés dans l'objet
            if not _subject_matches(subject):
                continue

            body_content = msg.get("body", {}).get("content", "")
            email, prenom, nom = _extract_from_wordpress_body(body_content)

            # Corps non parsable ou ligne "De :" absente : email ignoré
            if not email:
                continue

            results.append({
                "email": email,
                "prenom": prenom,
                "nom": nom,
                "received_at": msg.get("receivedDateTime", ""),
            })

        # Mise à jour du timestamp après traitement pour le prochain cycle
        _save_last_check(now_iso)
        return results

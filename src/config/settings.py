"""
Configuration centralisée du projet MailFlow.

Toutes les variables sont lues depuis le fichier .env à la racine du projet.
Les valeurs par défaut sont indiquées pour les variables non critiques.

Variables obligatoires (vérifiées au démarrage par validate_config) :
  - MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_USER_EMAIL
  - GOOGLE_SHEET_ID, GOOGLE_DOC_CONTENU_MESSAGE_ID
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Chargement du .env situé trois niveaux au-dessus (racine du projet)
load_dotenv(Path(__file__).parent.parent.parent / ".env")


# ---------------------------------------------------------------------------
# Microsoft Graph API — boite Outlook
# ---------------------------------------------------------------------------
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "")


# ---------------------------------------------------------------------------
# Google APIs — Sheets et Drive
# ---------------------------------------------------------------------------
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "src/config/credentials/google_service_account.json",
)
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "Liste_envois_MEMENTO")
GOOGLE_DOC_CONTENU_MESSAGE_ID = os.getenv("GOOGLE_DOC_CONTENU_MESSAGE_ID", "")


# ---------------------------------------------------------------------------
# Paramètres des agents (intervalles de polling)
# ---------------------------------------------------------------------------
ANALYSEUR_MAIL_INTERVAL = int(os.getenv("ANALYSEUR_MAIL_INTERVAL", 300))  # 5 min
EXPEDITEUR_INTERVAL = int(os.getenv("EXPEDITEUR_INTERVAL", 420))          # 7 min
FILTER_SENDER = os.getenv("FILTER_SENDER", "formulaire@exemple.fr")


# ---------------------------------------------------------------------------
# Mots-clés de l'objet email à détecter (condition OR)
# Couvre les variantes avec et sans accent sur "Mémento"
# ---------------------------------------------------------------------------
SUBJECT_KEYWORDS = [
    "demande memento",
    "demande mémento",
    "demande d'accès au memento",
    "demande d'accès au mémento",
    "demande accès memento",
    "demande accès mémento",
    "accès memento",
    "accès mémento",
]


# ---------------------------------------------------------------------------
# Mapping des colonnes du Google Sheet (index 0-based)
# Ordre réel : A=Email | B=Nom | C=Prenom | D=Approuver envoi? | E=Statut | F=Date
# ---------------------------------------------------------------------------
COL_EMAIL = 0      # A — adresse email du demandeur
COL_NOM = 1        # B — nom (en majuscules)
COL_PRENOM = 2     # C — prénom (title case)
COL_APPROUVER = 3  # D — rempli manuellement : OUI / NON
COL_STATUT = 4     # E — En attente / Envoyé
COL_DATE = 5       # F — timestamp jj/mm/aaaa hh:mm

STATUT_EN_ATTENTE = "En attente"
STATUT_ENVOYE = "Envoyé"


# ---------------------------------------------------------------------------
# Validation de la configuration au démarrage
# ---------------------------------------------------------------------------

def validate_config() -> list[str]:
    """
    Vérifie que toutes les variables d'environnement obligatoires sont renseignées.

    Returns:
        Liste des noms de variables manquantes (vide si tout est configuré).
    """
    required = {
        "MS_TENANT_ID": MS_TENANT_ID,
        "MS_CLIENT_ID": MS_CLIENT_ID,
        "MS_CLIENT_SECRET": MS_CLIENT_SECRET,
        "MS_USER_EMAIL": MS_USER_EMAIL,
        "GOOGLE_SHEET_ID": GOOGLE_SHEET_ID,
        "GOOGLE_DOC_CONTENU_MESSAGE_ID": GOOGLE_DOC_CONTENU_MESSAGE_ID,
    }
    return [name for name, value in required.items() if not value]

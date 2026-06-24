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
# LLM local — Ollama sur VPS
# ---------------------------------------------------------------------------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "ollama/llama3.1")


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
# Mapping des colonnes du Google Sheet (index 0-based, 14 colonnes A → N)
#
# Colonnes remplies par l'agent :
#   A=Devis | B=Société | C=Contact | E=E-mail | M=Statut | N=Date enregistrement
#
# Colonnes remplies manuellement :
#   D=Tél. | F=PME | G=Visites entreprises | H=Visites centres | I=Autres visites
#   J=Téléchargement études | K=Projet | L=Approuver envoi ?
# ---------------------------------------------------------------------------
COL_DEVIS = 0      # A — année en cours (ex. 2026), auto
COL_SOCIETE = 1    # B — nom société extrait du domaine email, auto
COL_CONTACT = 2    # C — "Prénom NOM" dans une cellule, auto
COL_TEL = 3        # D — téléphone, manuel
COL_EMAIL = 4      # E — adresse e-mail du demandeur, auto
COL_PME = 5        # F — PME, manuel
COL_VISITES_ENT = 6   # G — visites d'entreprises, manuel
COL_VISITES_CTR = 7   # H — visites de centres de compétences, manuel
COL_AUTRES_VIS = 8    # I — autres visites, manuel
COL_TELECHARGEMENT = 9  # J — téléchargement études, manuel
COL_PROJET = 10    # K — projet, manuel
COL_APPROUVER = 11  # L — rempli manuellement : OUI / NON
COL_STATUT = 12    # M — En attente / Envoyé, auto
COL_DATE = 13      # N — timestamp jj/mm/aaaa hh:mm, auto

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

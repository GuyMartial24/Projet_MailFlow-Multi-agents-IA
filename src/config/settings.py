import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


# ── Microsoft Graph API ─────────────────────────────────────
MS_TENANT_ID     = os.getenv("MS_TENANT_ID", "")
MS_CLIENT_ID     = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
MS_USER_EMAIL    = os.getenv("MS_USER_EMAIL", "")

# ── Google APIs ─────────────────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_JSON    = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "src/config/credentials/google_service_account.json")
GOOGLE_SHEET_ID                = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_TAB               = os.getenv("GOOGLE_SHEET_TAB", "Liste_envois_MEMENTO")
GOOGLE_DOC_CONTENU_MESSAGE_ID  = os.getenv("GOOGLE_DOC_CONTENU_MESSAGE_ID", "")

# ── Paramètres agents ───────────────────────────────────────
ANALYSEUR_MAIL_INTERVAL = int(os.getenv("ANALYSEUR_MAIL_INTERVAL", 300))   # secondes
EXPEDITEUR_INTERVAL     = int(os.getenv("EXPEDITEUR_INTERVAL", 420))       # secondes
FILTER_SENDER           = os.getenv("FILTER_SENDER", "formulaire@exemple.fr")

# ── Mots-clés objet email (OR entre eux) ────────────────────
SUBJECT_KEYWORDS = [
    "demande memento",
    "demande d'accès au memento",
    "demande accès memento",
    "accès memento",
]

# ── Colonnes Google Sheet (index 0-based) ───────────────────
# Ordre réel du fichier : A=Email B=Nom C=Prenom D=Approuver envoi? E=Statut F=Date enregistrement
COL_EMAIL       = 0   # A
COL_NOM         = 1   # B
COL_PRENOM      = 2   # C
COL_APPROUVER   = 3   # D — rempli manuellement : OUI / NON
COL_STATUT      = 4   # E — En attente / Envoyé
COL_DATE        = 5   # F — timestamp jj/mm/aaaa hh:mm

STATUT_EN_ATTENTE = "En attente"
STATUT_ENVOYE     = "Envoyé"


def validate_config() -> list[str]:
    """Retourne la liste des variables obligatoires non renseignées."""
    required = {
        "MS_TENANT_ID":                    MS_TENANT_ID,
        "MS_CLIENT_ID":                    MS_CLIENT_ID,
        "MS_CLIENT_SECRET":                MS_CLIENT_SECRET,
        "MS_USER_EMAIL":                   MS_USER_EMAIL,
        "GOOGLE_SHEET_ID":                GOOGLE_SHEET_ID,
        "GOOGLE_DOC_CONTENU_MESSAGE_ID":  GOOGLE_DOC_CONTENU_MESSAGE_ID,
    }
    return [name for name, value in required.items() if not value]

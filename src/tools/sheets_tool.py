"""
Outil Google Sheets API.

Fournit trois outils CrewAI pour interagir avec le Google Sheet de suivi :
  - SheetAppendTool        : insère une nouvelle ligne (agent analyseur_mail)
  - SheetReadPendingTool   : lit les lignes à traiter (agent expediteur)
  - SheetUpdateStatusTool  : met à jour le statut après envoi (agent expediteur)

Structure du Google Sheet (14 colonnes A → N) :
  A=Devis        | B=Société   | C=Contact  | D=Tél.       | E=E-mail
  F=PME          | G=Visites entreprises     | H=Visites centres compétences
  I=Autres vis.  | J=Téléchargement études   | K=Projet
  L=Approuver envoi ? | M=Statut | N=Date enregistrement demande Memento

Colonnes auto (agent) : A, B, C, E, M, N
Colonnes manuelles    : D, F, G, H, I, J, K, L
"""

from datetime import datetime

from crewai.tools import BaseTool
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from config import settings

# Scope en écriture pour les opérations d'ajout et de mise à jour
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Nombre total de colonnes du sheet (A=0 … N=13)
TOTAL_COLUMNS = 14


# ---------------------------------------------------------------------------
# Client Google Sheets
# ---------------------------------------------------------------------------

def _get_sheets_service():
    """
    Crée et retourne un client authentifié Google Sheets v4.

    Returns:
        Resource: client Google Sheets prêt à l'emploi.
    """
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _sheet_range(col_start: str = "A", col_end: str = "N") -> str:
    """
    Construit la plage A1 notation pour l'onglet configuré.

    Args:
        col_start: lettre de la colonne de départ (défaut 'A').
        col_end:   lettre de la colonne de fin (défaut 'N').

    Returns:
        Plage au format 'NomOnglet!A:N'.
    """
    return f"{settings.GOOGLE_SHEET_TAB}!{col_start}:{col_end}"


# ---------------------------------------------------------------------------
# Extraction du nom de société depuis le domaine email
# ---------------------------------------------------------------------------

def _extract_company(email: str) -> str:
    """
    Extrait le nom de la société depuis le domaine de l'adresse email.

    Algorithme :
      1. Récupère la partie après '@'           → 'acme.com'
      2. Supprime le TLD (.com, .fr, .org…)    → 'acme'
      3. Applique le title case                 → 'Acme'

    Exemples :
      - sophie@acme.com       → 'Acme'
      - contact@boisexemple.fr             → 'Boisexemple'
      - info@foretexemple.com → 'Foretexemple'

    Note : le résultat est une approximation destinée à être corrigée
    manuellement si nécessaire.

    Args:
        email: adresse email du demandeur.

    Returns:
        Nom de société en title case, ou chaîne vide si extraction impossible.
    """
    try:
        domain = email.split("@")[1]      # 'acme.com'
        company_raw = domain.split(".")[0]  # 'acme'
        return company_raw.title()          # 'Acme'
    except IndexError:
        return ""


# ---------------------------------------------------------------------------
# Tool : insertion d'une nouvelle ligne
# ---------------------------------------------------------------------------

class SheetAppendInput(BaseModel):
    """Schéma d'entrée pour l'ajout d'une ligne dans le Google Sheet."""

    email: str = Field(description="Adresse e-mail du demandeur")
    prenom: str = Field(description="Prénom du demandeur")
    nom: str = Field(description="Nom du demandeur")


class SheetAppendTool(BaseTool):
    """
    Outil CrewAI pour insérer une nouvelle demande dans le Google Sheet.

    Colonnes remplies automatiquement :
      - A (Devis)    : année en cours (ex. '2026')
      - B (Société)  : nom extrait du domaine email (title case)
      - C (Contact)  : 'Prénom NOM' dans une cellule
      - E (E-mail)   : adresse email brute
      - M (Statut)   : 'En attente'
      - N (Date)     : timestamp jj/mm/aaaa hh:mm

    Colonnes laissées vides (remplissage manuel) : D, F, G, H, I, J, K, L
    """

    name: str = "sheet_append_row"
    description: str = (
        "Ajoute une nouvelle ligne dans le Google Sheet. "
        "Remplit automatiquement : Devis (année), Société (domaine email), "
        "Contact (Prénom NOM), E-mail, Statut ('En attente') et Date. "
        "Les autres colonnes sont laissées vides pour saisie manuelle."
    )
    args_schema: type[BaseModel] = SheetAppendInput

    def _run(self, email: str, prenom: str, nom: str) -> str:
        """
        Construit et insère la ligne dans le Google Sheet.

        Args:
            email:  adresse e-mail du demandeur.
            prenom: prénom brut (sera mis en title case).
            nom:    nom brut (sera mis en majuscules).

        Returns:
            Message de confirmation avec les données insérées et le timestamp.
        """
        service = _get_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        year = str(datetime.now().year)  # ex. '2026'

        # Normalisation de la casse
        prenom_fmt = prenom.title()   # 'jean' → 'Jean'
        nom_fmt = nom.upper()         # 'dupont' → 'DUPONT'
        contact = f"{prenom_fmt} {nom_fmt}"  # 'Jean DUPONT'

        # Extraction du nom de société depuis le domaine de l'email
        societe = _extract_company(email)

        # Construction de la ligne sur 14 colonnes (A → N)
        # Les colonnes manuelles (D, F-K, L) sont initialisées à vide
        row = [""] * TOTAL_COLUMNS
        row[settings.COL_DEVIS] = year
        row[settings.COL_SOCIETE] = societe
        row[settings.COL_CONTACT] = contact
        row[settings.COL_EMAIL] = email
        row[settings.COL_STATUT] = settings.STATUT_EN_ATTENTE
        row[settings.COL_DATE] = now

        service.spreadsheets().values().append(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        return (
            f"Ligne ajoutée : {contact} <{email}> | "
            f"Société : {societe} | Devis : {year} | {now}"
        )


# ---------------------------------------------------------------------------
# Tool : lecture des lignes à traiter
# ---------------------------------------------------------------------------

class SheetReadPendingInput(BaseModel):
    """Schéma d'entrée du tool (aucun paramètre requis)."""

    dummy: str = Field(default="", description="Pas de paramètre requis.")


class SheetReadPendingTool(BaseTool):
    """
    Outil CrewAI pour lire les demandes approuvées en attente d'envoi.

    Filtre les lignes du Google Sheet où :
      - Colonne L (Approuver envoi ?) = 'OUI' (insensible à la casse)
      - Colonne M (Statut) = 'En attente'

    Ce double filtre garantit qu'aucun email n'est envoyé deux fois.
    """

    name: str = "sheet_read_pending_rows"
    description: str = (
        "Lit le Google Sheet et retourne toutes les lignes où "
        "'Approuver envoi ?' (col L) = 'OUI' ET 'Statut' (col M) = 'En attente'. "
        "Retourne une liste de dicts {row_index, email, contact}."
    )
    args_schema: type[BaseModel] = SheetReadPendingInput

    def _run(self, dummy: str = "") -> list[dict]:
        """
        Parcourt le Google Sheet et retourne les lignes éligibles à l'envoi.

        Args:
            dummy: paramètre inutilisé (requis par l'interface BaseTool).

        Returns:
            Liste de dicts {row_index, email, contact}.
            row_index est 1-based (convention API Google Sheets).
        """
        service = _get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
        ).execute()

        rows = result.get("values", [])
        pending = []

        for i, row in enumerate(rows):
            # Ligne 0 = en-tête du tableau → ignorée
            if i == 0:
                continue

            # Compléter les colonnes manquantes jusqu'à la colonne M (index 12)
            while len(row) <= settings.COL_STATUT:
                row.append("")

            approuver = row[settings.COL_APPROUVER].strip().upper()
            statut = row[settings.COL_STATUT].strip()

            # Double condition : approuvé manuellement ET pas encore envoyé
            if approuver == "OUI" and statut == settings.STATUT_EN_ATTENTE:
                pending.append({
                    "row_index": i + 1,  # 1-based pour l'API Sheets
                    "email": row[settings.COL_EMAIL] if len(row) > settings.COL_EMAIL else "",
                    "contact": row[settings.COL_CONTACT] if len(row) > settings.COL_CONTACT else "",
                })

        return pending


# ---------------------------------------------------------------------------
# Tool : mise à jour du statut après envoi
# ---------------------------------------------------------------------------

class SheetUpdateStatusInput(BaseModel):
    """Schéma d'entrée pour la mise à jour du statut d'une ligne."""

    row_index: int = Field(description="Index 1-based de la ligne à mettre à jour")


class SheetUpdateStatusTool(BaseTool):
    """
    Outil CrewAI pour passer le statut d'une ligne de 'En attente' à 'Envoyé'.

    Met à jour la cellule de la colonne M (Statut).
    Doit être appelé immédiatement après chaque envoi email réussi.
    """

    name: str = "sheet_update_status_envoye"
    description: str = (
        "Met à jour la colonne M (Statut) d'une ligne donnée : "
        "'En attente' → 'Envoyé'. "
        "À appeler immédiatement après chaque envoi email réussi."
    )
    args_schema: type[BaseModel] = SheetUpdateStatusInput

    def _run(self, row_index: int) -> str:
        """
        Met à jour la cellule Statut (colonne M) de la ligne spécifiée.

        Args:
            row_index: numéro de ligne 1-based (tel que retourné par SheetReadPendingTool).

        Returns:
            Message de confirmation avec le numéro de ligne et le nouveau statut.
        """
        service = _get_sheets_service()

        # COL_STATUT = 12 → lettre 'M' (A=0, B=1, ... M=12)
        col_letter = chr(ord("A") + settings.COL_STATUT)
        cell_range = f"{settings.GOOGLE_SHEET_TAB}!{col_letter}{row_index}"

        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[settings.STATUT_ENVOYE]]},
        ).execute()

        return f"Ligne {row_index} → Statut mis à jour : {settings.STATUT_ENVOYE}"

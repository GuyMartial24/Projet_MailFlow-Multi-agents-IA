"""
Outil Google Sheets API.

Fournit trois outils CrewAI pour interagir avec le Google Sheet de suivi :
  - SheetAppendTool        : insère une nouvelle ligne (agent analyseur_mail)
  - SheetReadPendingTool   : lit les lignes à traiter (agent expediteur)
  - SheetUpdateStatusTool  : met à jour le statut après envoi (agent expediteur)

Structure du Google Sheet :
  A=Email | B=Nom | C=Prenom | D=Approuver envoi? | E=Statut | F=Date enregistrement
"""

from datetime import datetime

from crewai.tools import BaseTool
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from config import settings

# Scope en écriture pour les opérations d'ajout et de mise à jour
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ---------------------------------------------------------------------------
# Client Google Sheets
# ---------------------------------------------------------------------------

def _get_sheets_service():
    """
    Crée et retourne un client authentifié Google Sheets v4.

    Utilise le compte de service dont le chemin JSON est défini dans
    settings.GOOGLE_SERVICE_ACCOUNT_JSON.

    Returns:
        Resource: client Google Sheets prêt à l'emploi.
    """
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _sheet_range(col_start: str = "A", col_end: str = "F") -> str:
    """
    Construit la plage A1 notation pour l'onglet configuré.

    Args:
        col_start: lettre de la colonne de départ (défaut 'A').
        col_end:   lettre de la colonne de fin (défaut 'F').

    Returns:
        Plage au format 'NomOnglet!A:F'.
    """
    return f"{settings.GOOGLE_SHEET_TAB}!{col_start}:{col_end}"


# ---------------------------------------------------------------------------
# Tool : insertion d'une nouvelle ligne
# ---------------------------------------------------------------------------

class SheetAppendInput(BaseModel):
    """Schéma d'entrée pour l'ajout d'une ligne dans le Google Sheet."""

    email: str = Field(description="Adresse email du demandeur")
    prenom: str = Field(description="Prénom du demandeur")
    nom: str = Field(description="Nom du demandeur")


class SheetAppendTool(BaseTool):
    """
    Outil CrewAI pour insérer une nouvelle demande dans le Google Sheet.

    Normalise automatiquement la casse :
      - Prénom : title case (ex. 'jean' → 'Jean', 'jean-pierre' → 'Jean-Pierre')
      - NOM    : majuscules (ex. 'dupont' → 'DUPONT')

    Les colonnes 'Approuver envoi ?' et 'Statut' sont gérées séparément :
      - 'Approuver envoi ?' : laissée vide (remplie manuellement)
      - 'Statut' : initialisé à 'En attente' automatiquement
    """

    name: str = "sheet_append_row"
    description: str = (
        "Ajoute une nouvelle ligne dans le Google Sheet avec l'email, le prénom, "
        "le NOM, la date d'enregistrement (timestamp auto) et le statut 'En attente'. "
        "La colonne 'Approuver envoi ?' est laissée vide pour validation manuelle."
    )
    args_schema: type[BaseModel] = SheetAppendInput

    def _run(self, email: str, prenom: str, nom: str) -> str:
        """
        Insère la ligne dans le Google Sheet avec normalisation de la casse.

        Args:
            email:  adresse email du demandeur.
            prenom: prénom brut (sera mis en title case).
            nom:    nom brut (sera mis en majuscules).

        Returns:
            Message de confirmation avec les données insérées et le timestamp.
        """
        service = _get_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Normalisation de la casse avant insertion
        prenom_fmt = prenom.title()   # 'jean' → 'Jean', 'jean-pierre' → 'Jean-Pierre'
        nom_fmt = nom.upper()         # 'dupont' → 'DUPONT'

        # Ordre des colonnes : A=Email | B=Nom | C=Prenom | D=vide | E=Statut | F=Date
        row = [email, nom_fmt, prenom_fmt, "", settings.STATUT_EN_ATTENTE, now]

        service.spreadsheets().values().append(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        return f"Ligne ajoutée : {prenom_fmt} {nom_fmt} <{email}> — {now}"


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
      - Colonne D (Approuver envoi ?) = 'OUI' (insensible à la casse)
      - Colonne E (Statut) = 'En attente'

    Ce double filtre garantit qu'aucun email n'est envoyé deux fois :
    une ligne déjà traitée a son statut à 'Envoyé' et est donc ignorée.
    """

    name: str = "sheet_read_pending_rows"
    description: str = (
        "Lit le Google Sheet et retourne toutes les lignes où "
        "'Approuver envoi ?' = 'OUI' ET 'Statut' = 'En attente'. "
        "Retourne une liste de dicts {row_index, email, prenom, nom}."
    )
    args_schema: type[BaseModel] = SheetReadPendingInput

    def _run(self, dummy: str = "") -> list[dict]:
        """
        Parcourt le Google Sheet et retourne les lignes éligibles à l'envoi.

        La ligne 0 (en-tête) est ignorée. Les colonnes manquantes sont
        complétées avec des chaînes vides pour éviter les erreurs d'index.

        Args:
            dummy: paramètre inutilisé (requis par l'interface BaseTool).

        Returns:
            Liste de dicts {row_index, email, prenom, nom}.
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

            # Compléter les colonnes manquantes (lignes partiellement remplies)
            while len(row) <= settings.COL_STATUT:
                row.append("")

            approuver = row[settings.COL_APPROUVER].strip().upper()
            statut = row[settings.COL_STATUT].strip()

            # Double condition : approuvé manuellement ET pas encore envoyé
            if approuver == "OUI" and statut == settings.STATUT_EN_ATTENTE:
                pending.append({
                    "row_index": i + 1,  # Conversion en index 1-based pour l'API Sheets
                    "email": row[settings.COL_EMAIL],
                    "prenom": row[settings.COL_PRENOM],
                    "nom": row[settings.COL_NOM],
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

    Doit être appelé immédiatement après chaque envoi email réussi
    pour éviter qu'une ligne soit traitée à nouveau au prochain cycle.
    """

    name: str = "sheet_update_status_envoye"
    description: str = (
        "Met à jour la colonne Statut d'une ligne donnée : 'En attente' → 'Envoyé'. "
        "À appeler immédiatement après chaque envoi email réussi."
    )
    args_schema: type[BaseModel] = SheetUpdateStatusInput

    def _run(self, row_index: int) -> str:
        """
        Met à jour la cellule Statut de la ligne spécifiée.

        Args:
            row_index: numéro de ligne 1-based (tel que retourné par SheetReadPendingTool).

        Returns:
            Message de confirmation avec le numéro de ligne et le nouveau statut.
        """
        service = _get_sheets_service()

        # Calcul de la lettre de colonne : COL_STATUT=4 → 'E'
        col_letter = chr(ord("A") + settings.COL_STATUT)
        cell_range = f"{settings.GOOGLE_SHEET_TAB}!{col_letter}{row_index}"

        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[settings.STATUT_ENVOYE]]},
        ).execute()

        return f"Ligne {row_index} → Statut mis à jour : {settings.STATUT_ENVOYE}"

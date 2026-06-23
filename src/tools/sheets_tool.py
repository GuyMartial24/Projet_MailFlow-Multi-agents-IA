"""
Outil Google Sheets API.

Responsabilités :
- Ajouter une nouvelle ligne (agent analyseur_mail)
- Lire les lignes à traiter : Approuver envoi = OUI et Statut = En attente (agent expediteur)
- Mettre à jour le Statut → Envoyé après envoi (agent expediteur)
"""

from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _sheet_range(col_start: str = "A", col_end: str = "F") -> str:
    return f"{settings.GOOGLE_SHEET_TAB}!{col_start}:{col_end}"


# ── Tool : ajout d'une ligne ─────────────────────────────────

class SheetAppendInput(BaseModel):
    email:  str = Field(description="Adresse email du demandeur")
    prenom: str = Field(description="Prénom du demandeur")
    nom:    str = Field(description="Nom du demandeur")


class SheetAppendTool(BaseTool):
    name: str = "sheet_append_row"
    description: str = (
        "Ajoute une nouvelle ligne dans le Google Sheet avec l'email, le prénom, le nom, "
        "la date d'enregistrement (timestamp auto) et le statut 'En attente'. "
        "Les colonnes Approuver envoi et Statut sont gérées séparément."
    )
    args_schema: type[BaseModel] = SheetAppendInput

    def _run(self, email: str, prenom: str, nom: str) -> str:
        service = _get_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Ordre réel : A=Email | B=Nom | C=Prenom | D=Approuver envoi? | E=Statut | F=Date enregistrement
        row = [email, nom, prenom, "", settings.STATUT_EN_ATTENTE, now]

        service.spreadsheets().values().append(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        return f"Ligne ajoutée : {prenom} {nom} <{email}> — {now}"


# ── Tool : lecture des lignes à traiter ──────────────────────

class SheetReadPendingInput(BaseModel):
    dummy: str = Field(default="", description="Pas de paramètre requis.")


class SheetReadPendingTool(BaseTool):
    name: str = "sheet_read_pending_rows"
    description: str = (
        "Lit le Google Sheet et retourne toutes les lignes où "
        "'Approuver envoi' = 'OUI' ET 'Statut' = 'En attente'. "
        "Retourne une liste de dicts {row_index, email, prenom, nom}."
    )
    args_schema: type[BaseModel] = SheetReadPendingInput

    def _run(self, dummy: str = "") -> list[dict]:
        service = _get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
        ).execute()

        rows = result.get("values", [])
        pending = []

        for i, row in enumerate(rows):
            # Ignorer la ligne d'en-tête (ligne 0)
            if i == 0:
                continue
            # Compléter les colonnes manquantes avec des chaînes vides
            while len(row) <= settings.COL_STATUT:
                row.append("")

            approuver = row[settings.COL_APPROUVER].strip().upper()
            statut    = row[settings.COL_STATUT].strip()

            if approuver == "OUI" and statut == settings.STATUT_EN_ATTENTE:
                pending.append({
                    "row_index": i + 1,  # 1-based pour l'API Sheets
                    "email":     row[settings.COL_EMAIL],
                    "prenom":    row[settings.COL_PRENOM],
                    "nom":       row[settings.COL_NOM],
                })

        return pending


# ── Tool : mise à jour Statut → Envoyé ───────────────────────

class SheetUpdateStatusInput(BaseModel):
    row_index: int = Field(description="Index 1-based de la ligne à mettre à jour")


class SheetUpdateStatusTool(BaseTool):
    name: str = "sheet_update_status_envoye"
    description: str = (
        "Met à jour la colonne Statut d'une ligne donnée : 'En attente' → 'Envoyé'."
    )
    args_schema: type[BaseModel] = SheetUpdateStatusInput

    def _run(self, row_index: int) -> str:
        service = _get_sheets_service()

        # Colonne E (index 4) = Statut
        col_letter = chr(ord("A") + settings.COL_STATUT)  # "E"
        cell_range = f"{settings.GOOGLE_SHEET_TAB}!{col_letter}{row_index}"

        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[settings.STATUT_ENVOYE]]},
        ).execute()

        return f"Ligne {row_index} → Statut mis à jour : {settings.STATUT_ENVOYE}"

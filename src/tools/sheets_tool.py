"""
Outil Google Sheets API.

Fournit six outils CrewAI pour interagir avec le Google Sheet de suivi :

  Agent analyseur_mail :
    - SheetFindEmailTool       : vérifie si un email existe déjà dans le Sheet
    - SheetAppendTool          : insère une nouvelle ligne (1ère demande)
    - SheetMarkRedondanceTool  : signale une redondance (O + P) sur une ligne existante

  Agent expediteur :
    - SheetReadPendingTool     : lit les lignes à traiter (1er envoi + renvois)
    - SheetUpdateStatusTool    : passe Statut → 'Envoyé'
    - SheetIncrementEnvoisTool : incrémente Q (Nombre d'envois déjà effectués)
    - SheetClearRedondanceTool : remet O à vide après un renvoi traité

Structure du Google Sheet (17 colonnes A → Q) :
  A=Devis | B=Société | C=Contact | D=Tél. | E=E-mail
  F=PME | G=Visites ent. | H=Visites centres | I=Autres vis. | J=Téléchargement | K=Projet
  L=Approuver envoi ? | M=Statut | N=Date 1ère demande
  O=Gestion redondances | P=Date dernière demande | Q=Nb envois effectués
"""

from datetime import datetime

from crewai.tools import BaseTool
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOTAL_COLUMNS = 17  # Colonnes A (0) → Q (16)


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


def _sheet_range(col_start: str = "A", col_end: str = "Q") -> str:
    """
    Construit la plage A1 notation pour l'onglet configuré.

    Args:
        col_start: lettre de la colonne de départ (défaut 'A').
        col_end:   lettre de la colonne de fin (défaut 'Q').

    Returns:
        Plage au format 'NomOnglet!A:Q'.
    """
    return f"{settings.GOOGLE_SHEET_TAB}!{col_start}:{col_end}"


def _col_letter(col_index: int) -> str:
    """Convertit un index 0-based en lettre de colonne (0→'A', 16→'Q')."""
    return chr(ord("A") + col_index)


def _pad_row(row: list, length: int = TOTAL_COLUMNS) -> list:
    """Complète une ligne avec des chaînes vides jusqu'à la longueur cible."""
    while len(row) < length:
        row.append("")
    return row


# ---------------------------------------------------------------------------
# Extraction du nom de société depuis le domaine email
# ---------------------------------------------------------------------------

def _extract_company(email: str) -> str:
    """
    Extrait le nom de la société depuis le domaine de l'adresse email.

    Algorithme : partie avant le TLD, mise en title case.
    Exemple : sophie@acme.com → 'Acme'

    Args:
        email: adresse email du demandeur.

    Returns:
        Nom de société en title case, ou chaîne vide si extraction impossible.
    """
    try:
        domain = email.split("@")[1]
        return domain.split(".")[0].title()
    except IndexError:
        return ""


# ---------------------------------------------------------------------------
# Tool : recherche d'un email existant dans le Sheet
# ---------------------------------------------------------------------------

class SheetFindEmailInput(BaseModel):
    """Schéma d'entrée pour la recherche d'un email dans le Google Sheet."""

    email: str = Field(description="Adresse e-mail à rechercher dans la colonne E")


class SheetFindEmailTool(BaseTool):
    """
    Outil CrewAI pour vérifier si un email est déjà présent dans le Google Sheet.

    Parcourt la colonne E et retourne les informations de la ligne si trouvée :
    statut, approbation, valeur de la colonne O (redondance) et nombre d'envois.

    Utilisé par l'agent analyseur_mail avant toute insertion pour détecter :
      - Un doublon en cours (Statut = 'En attente')
      - Une redondance d'un contact déjà servi (Approuver=OUI + Statut='Envoyé')
    """

    name: str = "sheet_find_email"
    description: str = (
        "Vérifie si une adresse e-mail est déjà présente dans le Google Sheet. "
        "Retourne un dict {found, row_index, statut, approuver, redondance, nb_envois}. "
        "found=False si absent, found=True avec les infos de la ligne si présent."
    )
    args_schema: type[BaseModel] = SheetFindEmailInput

    def _run(self, email: str) -> dict:
        """
        Recherche l'email dans la colonne E du Google Sheet.

        La comparaison est insensible à la casse.

        Args:
            email: adresse e-mail à rechercher.

        Returns:
            Dict avec found=False si absent, ou found=True + informations de la ligne.
        """
        service = _get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
        ).execute()

        rows = result.get("values", [])
        email_lower = email.strip().lower()

        for i, row in enumerate(rows):
            if i == 0:  # Ignorer la ligne d'en-tête
                continue
            row = _pad_row(row)

            if row[settings.COL_EMAIL].strip().lower() == email_lower:
                return {
                    "found": True,
                    "row_index": i + 1,  # 1-based
                    "statut": row[settings.COL_STATUT].strip(),
                    "approuver": row[settings.COL_APPROUVER].strip().upper(),
                    "redondance": row[settings.COL_REDONDANCE].strip(),
                    "nb_envois": row[settings.COL_NB_ENVOIS].strip(),
                }

        return {"found": False}


# ---------------------------------------------------------------------------
# Tool : insertion d'une nouvelle ligne (1ère demande)
# ---------------------------------------------------------------------------

class SheetAppendInput(BaseModel):
    """Schéma d'entrée pour l'ajout d'une nouvelle ligne dans le Google Sheet."""

    email: str = Field(description="Adresse e-mail du demandeur")
    prenom: str = Field(description="Prénom du demandeur")
    nom: str = Field(description="Nom du demandeur")


class SheetAppendTool(BaseTool):
    """
    Outil CrewAI pour insérer une nouvelle demande (1ère fois) dans le Google Sheet.

    Colonnes remplies automatiquement :
      A (Devis)            : année en cours
      B (Société)          : nom extrait du domaine email
      C (Contact)          : 'Prénom NOM'
      E (E-mail)           : adresse email
      M (Statut)           : 'En attente'
      N (Date 1ère demande): timestamp jj/mm/aaaa hh:mm
      O, P, Q              : vides (seront remplis lors de redondances ou d'envois)

    Colonnes manuelles (D, F–K, L) : laissées vides.
    """

    name: str = "sheet_append_row"
    description: str = (
        "Insère une nouvelle ligne dans le Google Sheet pour une 1ère demande. "
        "Remplit automatiquement Devis, Société, Contact, E-mail, Statut et Date 1ère demande. "
        "À utiliser uniquement si SheetFindEmailTool confirme que l'email est absent."
    )
    args_schema: type[BaseModel] = SheetAppendInput

    def _run(self, email: str, prenom: str, nom: str) -> str:
        """
        Insère la ligne sur 17 colonnes avec les valeurs automatiques.

        Args:
            email:  adresse e-mail du demandeur.
            prenom: prénom brut (sera mis en title case).
            nom:    nom brut (sera mis en majuscules).

        Returns:
            Message de confirmation avec les données insérées.
        """
        service = _get_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        year = str(datetime.now().year)

        prenom_fmt = prenom.title()
        nom_fmt = nom.upper()
        contact = f"{prenom_fmt} {nom_fmt}"
        societe = _extract_company(email)

        # Construction de la ligne sur 17 colonnes — manuelles laissées vides
        row = [""] * TOTAL_COLUMNS
        row[settings.COL_DEVIS] = year
        row[settings.COL_SOCIETE] = societe
        row[settings.COL_CONTACT] = contact
        row[settings.COL_EMAIL] = email
        row[settings.COL_STATUT] = settings.STATUT_EN_ATTENTE
        row[settings.COL_DATE_PREMIERE] = now
        # O (COL_REDONDANCE), P (COL_DATE_DERNIERE), Q (COL_NB_ENVOIS) restent vides

        # Calcul de la prochaine ligne vide via la colonne A
        # (évite le décalage causé par append() quand des données existent au-delà de Q)
        col_a = service.spreadsheets().values().get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=f"{settings.GOOGLE_SHEET_TAB}!A:A",
        ).execute()
        next_row = len(col_a.get("values", [])) + 1

        # Écriture à la position exacte, garantie colonne A
        col_end = _col_letter(TOTAL_COLUMNS - 1)  # 'Q'
        target_range = (
            f"{settings.GOOGLE_SHEET_TAB}!A{next_row}:{col_end}{next_row}"
        )
        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=target_range,
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()

        return (
            f"Nouvelle ligne insérée : {contact} <{email}> | "
            f"Société : {societe} | Devis : {year} | {now}"
        )


# ---------------------------------------------------------------------------
# Tool : signalement d'une redondance sur une ligne existante
# ---------------------------------------------------------------------------

class SheetMarkRedondanceInput(BaseModel):
    """Schéma d'entrée pour le signalement d'une redondance."""

    row_index: int = Field(description="Index 1-based de la ligne à marquer")


class SheetMarkRedondanceTool(BaseTool):
    """
    Outil CrewAI pour signaler qu'un contact déjà servi a refait une demande.

    Met à jour deux cellules sur la ligne existante :
      - O (Gestion redondances)    : 'Envoyer à nouveau ?'
      - P (Date dernière demande)  : timestamp jj/mm/aaaa hh:mm

    L'opérateur voit alors la ligne dans le Sheet et décide :
      - Changer O → 'Oui' pour déclencher un renvoi par l'agent expediteur
      - Laisser tel quel pour ne rien faire
    """

    name: str = "sheet_mark_redondance"
    description: str = (
        "Signale une redondance sur une ligne existante : "
        "met O = 'Envoyer à nouveau ?' et P = timestamp de la nouvelle demande. "
        "À utiliser quand un contact (Approuver=OUI + Statut=Envoyé) refait une demande."
    )
    args_schema: type[BaseModel] = SheetMarkRedondanceInput

    def _run(self, row_index: int) -> str:
        """
        Met à jour les colonnes O et P de la ligne spécifiée.

        Args:
            row_index: numéro de ligne 1-based.

        Returns:
            Message de confirmation.
        """
        if row_index <= 1:
            return f"ERREUR : row_index={row_index} invalide — ligne 1 = en-tête protégée. Aucune modification."
        service = _get_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        tab = settings.GOOGLE_SHEET_TAB
        # Mise à jour en batch pour O et P en un seul appel API
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": [
                    {
                        "range": f"{tab}!{_col_letter(settings.COL_REDONDANCE)}{row_index}",
                        "values": [[settings.REDONDANCE_LABEL]],
                    },
                    {
                        "range": f"{tab}!{_col_letter(settings.COL_DATE_DERNIERE)}{row_index}",
                        "values": [[now]],
                    },
                ],
            },
        ).execute()

        return (
            f"Ligne {row_index} → O='{settings.REDONDANCE_LABEL}' | P={now}"
        )


# ---------------------------------------------------------------------------
# Tool : lecture des lignes à traiter (1er envoi + renvois)
# ---------------------------------------------------------------------------

class SheetReadPendingInput(BaseModel):
    """Schéma d'entrée du tool (aucun paramètre requis)."""

    dummy: str = Field(default="", description="Pas de paramètre requis.")


class SheetReadPendingTool(BaseTool):
    """
    Outil CrewAI pour lire les demandes en attente d'envoi.

    Détecte deux types de lignes éligibles :

    Type 'premier_envoi' :
      Approuver (L) = 'OUI' ET Statut (M) = 'En attente'

    Type 'renvoi' :
      Approuver (L) = 'OUI' ET Statut (M) = 'Envoyé' ET Redondance (O) = 'Oui'
      (l'opérateur a approuvé manuellement le renvoi)
    """

    name: str = "sheet_read_pending_rows"
    description: str = (
        "Lit le Google Sheet et retourne les lignes éligibles à l'envoi. "
        "Deux types : 'premier_envoi' (Approuver=OUI + Statut=En attente) "
        "et 'renvoi' (Approuver=OUI + Statut=Envoyé + O=Oui). "
        "Retourne une liste de dicts {row_index, email, contact, send_type}."
    )
    args_schema: type[BaseModel] = SheetReadPendingInput

    def _run(self, dummy: str = "") -> list[dict]:
        """
        Parcourt le Sheet et retourne les lignes éligibles avec leur type d'envoi.

        Args:
            dummy: paramètre inutilisé (requis par l'interface BaseTool).

        Returns:
            Liste de dicts {row_index, email, contact, send_type}.
        """
        service = _get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=_sheet_range(),
        ).execute()

        rows = result.get("values", [])
        pending = []

        for i, row in enumerate(rows):
            if i == 0:  # En-tête ignorée
                continue
            row = _pad_row(row)

            approuver = row[settings.COL_APPROUVER].strip().upper()
            statut = row[settings.COL_STATUT].strip()
            redondance = row[settings.COL_REDONDANCE].strip().upper()

            email = row[settings.COL_EMAIL]
            contact = row[settings.COL_CONTACT]
            row_index = i + 1  # 1-based

            # Condition 1 : premier envoi
            if approuver == "OUI" and statut == settings.STATUT_EN_ATTENTE:
                pending.append({
                    "row_index": row_index,
                    "email": email,
                    "contact": contact,
                    "send_type": "premier_envoi",
                })

            # Condition 2 : renvoi approuvé par l'opérateur
            elif (
                approuver == "OUI"
                and statut == settings.STATUT_ENVOYE
                and redondance == "OUI"
            ):
                pending.append({
                    "row_index": row_index,
                    "email": email,
                    "contact": contact,
                    "send_type": "renvoi",
                })

        return pending


# ---------------------------------------------------------------------------
# Tool : mise à jour du statut → 'Envoyé'
# ---------------------------------------------------------------------------

class SheetUpdateStatusInput(BaseModel):
    """Schéma d'entrée pour la mise à jour du statut."""

    row_index: int = Field(description="Index 1-based de la ligne à mettre à jour")


class SheetUpdateStatusTool(BaseTool):
    """
    Outil CrewAI pour passer le Statut (col M) de 'En attente' à 'Envoyé'.

    À appeler immédiatement après chaque envoi email réussi (premier envoi).
    """

    name: str = "sheet_update_status_envoye"
    description: str = (
        "Met à jour la colonne M (Statut) : 'En attente' → 'Envoyé'. "
        "À appeler après chaque premier envoi réussi."
    )
    args_schema: type[BaseModel] = SheetUpdateStatusInput

    def _run(self, row_index: int) -> str:
        """
        Met à jour la cellule Statut (colonne M) de la ligne spécifiée.

        Args:
            row_index: numéro de ligne 1-based.

        Returns:
            Message de confirmation.
        """
        if row_index <= 1:
            return f"ERREUR : row_index={row_index} invalide — ligne 1 = en-tête protégée. Aucune modification."
        service = _get_sheets_service()
        col = _col_letter(settings.COL_STATUT)  # 'M'
        cell_range = f"{settings.GOOGLE_SHEET_TAB}!{col}{row_index}"

        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[settings.STATUT_ENVOYE]]},
        ).execute()

        return f"Ligne {row_index} → Statut : {settings.STATUT_ENVOYE}"


# ---------------------------------------------------------------------------
# Tool : incrémentation du compteur d'envois (col Q)
# ---------------------------------------------------------------------------

class SheetIncrementEnvoisInput(BaseModel):
    """Schéma d'entrée pour l'incrémentation du compteur d'envois."""

    row_index: int = Field(description="Index 1-based de la ligne à incrémenter")


class SheetIncrementEnvoisTool(BaseTool):
    """
    Outil CrewAI pour incrémenter le compteur Q (Nombre d'envois déjà effectués).

    Appelé après CHAQUE envoi réussi (premier envoi ET renvois).
    Si la cellule est vide ou non numérique, elle est initialisée à 1.
    """

    name: str = "sheet_increment_envois"
    description: str = (
        "Incrémente de +1 la colonne Q (Nombre d'envois déjà effectués). "
        "À appeler après chaque envoi réussi (premier envoi et renvois). "
        "Initialise à 1 si la cellule est vide."
    )
    args_schema: type[BaseModel] = SheetIncrementEnvoisInput

    def _run(self, row_index: int) -> str:
        """
        Lit la valeur actuelle de Q, l'incrémente de 1 et écrit le résultat.

        Args:
            row_index: numéro de ligne 1-based.

        Returns:
            Message de confirmation avec la nouvelle valeur.
        """
        if row_index <= 1:
            return f"ERREUR : row_index={row_index} invalide — ligne 1 = en-tête protégée. Aucune modification."
        service = _get_sheets_service()
        col = _col_letter(settings.COL_NB_ENVOIS)  # 'Q'
        cell_range = f"{settings.GOOGLE_SHEET_TAB}!{col}{row_index}"

        # Lecture de la valeur actuelle
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
        ).execute()

        current_raw = result.get("values", [[""]])[0][0] if result.get("values") else ""

        try:
            current = int(current_raw)
        except (ValueError, TypeError):
            current = 0  # Cellule vide ou non numérique → on part de 0

        new_value = current + 1

        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[new_value]]},
        ).execute()

        return f"Ligne {row_index} → Nb envois : {new_value}"


# ---------------------------------------------------------------------------
# Tool : remise à zéro de la colonne O après un renvoi traité
# ---------------------------------------------------------------------------

class SheetClearRedondanceInput(BaseModel):
    """Schéma d'entrée pour la remise à zéro de la colonne O."""

    row_index: int = Field(description="Index 1-based de la ligne à nettoyer")


class SheetClearRedondanceTool(BaseTool):
    """
    Outil CrewAI pour vider la colonne O (Gestion redondances) après un renvoi traité.

    Évite qu'un renvoi soit déclenché en boucle à chaque cycle de l'expediteur.
    À appeler immédiatement après chaque renvoi réussi.
    """

    name: str = "sheet_clear_redondance"
    description: str = (
        "Remet la colonne O (Gestion redondances) à vide après un renvoi traité. "
        "Indispensable pour éviter qu'un renvoi soit déclenché en boucle. "
        "À appeler immédiatement après 'sheet_increment_envois' pour un renvoi."
    )
    args_schema: type[BaseModel] = SheetClearRedondanceInput

    def _run(self, row_index: int) -> str:
        """
        Vide la cellule O de la ligne spécifiée.

        Args:
            row_index: numéro de ligne 1-based.

        Returns:
            Message de confirmation.
        """
        if row_index <= 1:
            return f"ERREUR : row_index={row_index} invalide — ligne 1 = en-tête protégée. Aucune modification."
        service = _get_sheets_service()
        col = _col_letter(settings.COL_REDONDANCE)  # 'O'
        cell_range = f"{settings.GOOGLE_SHEET_TAB}!{col}{row_index}"

        service.spreadsheets().values().update(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[""]]},
        ).execute()

        return f"Ligne {row_index} → Colonne O remise à vide (renvoi traité)"

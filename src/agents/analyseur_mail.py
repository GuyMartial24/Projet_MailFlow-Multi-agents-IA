"""
Agent analyseur_mail.

Rôle : surveiller la boite Outlook de l'utilisateur toutes les 5 minutes,
détecter les emails de demande de Memento envoyés par WordPress,
et gérer l'insertion dans Google Sheets selon trois cas :

  Cas 1 — Email absent du Sheet :
      → Insertion nouvelle ligne (N=date, O/P/Q vides, Statut=En attente)

  Cas 2 — Email présent + Statut='En attente' (doublon en cours) :
      → Aucune insertion
      → Notification opérateur (log + email)

  Cas 3 — Email présent + Approuver=OUI + Statut='Envoyé' (déjà servi) :
      → Mise à jour ligne existante : O='Envoyer à nouveau ?', P=timestamp
      → Notification opérateur (log + email)

Flux global :
    Outlook → filtrage → SheetFindEmailTool → décision →
    SheetAppendTool (cas 1) | NotifyOperatorTool (cas 2) |
    SheetMarkRedondanceTool + NotifyOperatorTool (cas 3)
"""

from crewai import Agent, Task

from config.llm import get_llm
from tools.notify_tool import NotifyOperatorTool
from tools.outlook_tool import OutlookFetchTool
from tools.sheets_tool import (
    SheetAppendTool,
    SheetFindEmailTool,
    SheetMarkRedondanceTool,
)


def build_analyseur_mail_agent() -> Agent:
    """
    Instancie l'agent CrewAI chargé de la surveillance de la boite Outlook.

    Outils disponibles :
      - OutlookFetchTool       : récupère les nouveaux emails depuis la dernière exécution
      - SheetFindEmailTool     : vérifie si l'email existe déjà dans le Sheet
      - SheetAppendTool        : insère une nouvelle ligne (cas 1)
      - SheetMarkRedondanceTool: met O et P à jour sur ligne existante (cas 3)
      - NotifyOperatorTool     : notifie l'opérateur (cas 2 et 3)

    Returns:
        Agent: instance configurée et prête à recevoir une tâche.
    """
    return Agent(
        role="Analyste Email",
        goal=(
            "Surveiller la boite Outlook de l'utilisateur, détecter les nouveaux "
            "emails de formulaire@exemple.fr contenant une demande de Memento, "
            "et gérer intelligemment l'insertion dans le Google Sheet en distinguant "
            "les nouvelles demandes, les doublons en cours et les redondances de "
            "contacts déjà servis."
        ),
        backstory=(
            "Tu es un assistant de traitement des demandes d'accès au Memento. "
            "Tu surveilles en continu la boite email et tu extrais les informations "
            "du demandeur depuis la ligne 'De :' dans le corps du formulaire WordPress. "
            "Avant toute insertion, tu vérifies si l'email est déjà présent dans le "
            "Sheet pour éviter les doublons et gérer les redondances. "
            "Tu notifies l'opérateur par log et par email pour chaque anomalie détectée."
        ),
        tools=[
            OutlookFetchTool(),
            SheetFindEmailTool(),
            SheetAppendTool(),
            SheetMarkRedondanceTool(),
            NotifyOperatorTool(),
        ],
        llm=get_llm(),
        verbose=True,
        allow_delegation=False,
    )


def build_analyseur_mail_task(agent: Agent) -> Task:
    """
    Construit la tâche de l'agent analyseur_mail avec la logique des 3 cas.

    Args:
        agent: instance de l'agent à qui assigner la tâche.

    Returns:
        Task: tâche CrewAI prête à être exécutée.
    """
    return Task(
        description=(
            "IMPORTANT : utilise UNIQUEMENT les outils disponibles. "
            "N'écris pas de code Python. Ne génère pas de JSON inventé. "
            "Appelle les outils dans l'ordre indiqué ci-dessous.\n\n"
            "ÉTAPE 1 : Appelle l'outil 'outlook_fetch_new_emails'.\n"
            "  - Si la liste retournée est vide : termine et indique "
            "'Aucun nouveau message détecté'.\n"
            "  - Sinon : continue avec ÉTAPE 2 pour chaque email.\n\n"
            "ÉTAPE 2 : Pour chaque email de la liste, appelle 'sheet_find_email' "
            "avec l'adresse email exacte retournée par l'étape 1.\n\n"
            "ÉTAPE 3 : Selon le résultat de 'sheet_find_email' :\n"
            "  - Si found=False : appelle 'sheet_append_row' avec email, prenom, nom.\n"
            "  - Si found=True et statut='En attente' : appelle 'notify_operator' "
            "avec subject='Doublon détecté' et message indiquant l'email et le row_index.\n"
            "  - Si found=True et approuver='OUI' et statut='Envoyé' : appelle "
            "'sheet_mark_redondance' avec le row_index exact, puis appelle "
            "'notify_operator' avec subject='Redondance détectée'.\n\n"
            "ÉTAPE 4 : Indique le nombre d'insertions, doublons et redondances."
        ),
        expected_output=(
            "Texte simple indiquant : nombre d'emails traités, nombre d'insertions, "
            "nombre de doublons ignorés, nombre de redondances signalées."
        ),
        agent=agent,
    )

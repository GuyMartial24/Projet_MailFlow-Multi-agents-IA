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
            "1. Utilise 'outlook_fetch_new_emails' pour récupérer les nouveaux "
            "emails depuis la dernière vérification.\n"
            "2. Si aucun email n'est retourné, termine et indique 'Aucun nouveau "
            "message détecté'.\n"
            "3. Pour CHAQUE email retourné, applique la logique suivante :\n\n"
            "   a. Utilise 'sheet_find_email' pour vérifier si l'adresse email "
            "existe déjà dans le Google Sheet.\n\n"
            "   CAS 1 — email absent (found=False) :\n"
            "     → Utilise 'sheet_append_row' pour insérer une nouvelle ligne.\n\n"
            "   CAS 2 — email présent + Statut='En attente' (doublon en cours) :\n"
            "     → Ne rien insérer.\n"
            "     → Utilise 'notify_operator' avec :\n"
            "         subject='Doublon détecté'\n"
            "         message='[email] a déjà une demande En attente (ligne [row_index]). "
            "Aucune nouvelle ligne créée.'\n\n"
            "   CAS 3 — email présent + Approuver=OUI + Statut=Envoyé "
            "(contact déjà servi, nouvelle demande) :\n"
            "     → Utilise 'sheet_mark_redondance' avec le row_index de la ligne "
            "existante pour mettre O='Envoyer à nouveau ?' et P=timestamp.\n"
            "     → Utilise 'notify_operator' avec :\n"
            "         subject='Redondance détectée'\n"
            "         message='[email] a déjà reçu le Memento (ligne [row_index]). "
            "La colonne O a été mise à \"Envoyer à nouveau ?\". "
            "Mettez O=Oui pour déclencher un renvoi.'\n\n"
            "4. Rapporte un résumé : nombre d'insertions, doublons ignorés, "
            "redondances signalées."
        ),
        expected_output=(
            "Un résumé détaillé par email traité indiquant le cas détecté "
            "(insertion / doublon ignoré / redondance signalée) et le nombre "
            "total pour chaque catégorie."
        ),
        agent=agent,
    )

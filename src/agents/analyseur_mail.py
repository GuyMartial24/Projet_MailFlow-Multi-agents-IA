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

from config import settings
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
            f"emails de {settings.FILTER_SENDER} contenant une demande de Memento, "
            "et gérer intelligemment l'insertion dans le Google Sheet en distinguant "
            "les nouvelles demandes, les doublons en cours et les redondances de "
            "contacts déjà servis."
        ),
        backstory=(
            "LANGUE : Tu réponds TOUJOURS en français, sans exception. "
            "Toutes tes réponses, messages et rapports doivent être rédigés en français. "
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
            "LANGUE : Réponds TOUJOURS en français. "
            "Aucune réponse dans une autre langue n'est acceptée.\n\n"
            "IMPORTANT : utilise UNIQUEMENT les outils disponibles. "
            "N'écris pas de code Python. Ne génère pas de JSON inventé. "
            "Appelle les outils dans l'ordre indiqué ci-dessous.\n\n"
            "ÉTAPE 1 : Appelle l'outil 'outlook_fetch_new_emails'.\n"
            "  - Si la liste retournée est vide : termine et indique "
            "'Aucun nouveau message détecté'.\n"
            "  - Sinon : continue avec ÉTAPE 2 pour chaque email.\n\n"
            "ÉTAPE 2 : Pour chaque email de la liste, appelle 'sheet_find_email' "
            "avec l'adresse email exacte retournée par l'étape 1.\n\n"
            "ÉTAPE 3 : Selon le résultat de 'sheet_find_email' :\n\n"
            "  CAS 1 — found=False :\n"
            "    Appelle 'sheet_append_row' avec email, prenom, nom.\n\n"
            "  CAS 2 — found=True + statut='En attente' (doublon en cours) :\n"
            "    Appelle 'notify_operator' avec exactement :\n"
            "      subject = '[MailFlow] Doublon détecté — {EMAIL}'\n"
            "        (remplace {EMAIL} par l'adresse email exacte)\n"
            "      message = "
            "'⚠️ Alerte MailFlow\\n\\n"
            "Nouvelle demande reçue de :\\n"
            "  📧 {EMAIL}\\n"
            "  👤 {PRENOM} {NOM}\\n\\n"
            "Cette personne a déjà une demande EN ATTENTE (ligne {ROW}).\\n"
            "Aucune nouvelle ligne n'a été créée.\\n\\n"
            "✅ Actions disponibles :\\n"
            "→ Ne rien faire : la demande existante sera traitée normalement\\n"
            "→ Vérifier manuellement : Google Sheet > ligne {ROW}\\n\\n"
            "---\\nMessage automatique — Agent MailFlow'\n"
            "        (remplace {EMAIL}, {PRENOM}, {NOM}, {ROW} par les vraies valeurs)\n\n"
            "  CAS 3 — found=True + approuver='OUI' + statut='Envoyé' (déjà servi) :\n"
            "    D'abord appelle 'sheet_mark_redondance' avec le row_index exact.\n"
            "    Ensuite appelle 'notify_operator' avec exactement :\n"
            "      subject = '[MailFlow] Redondance détectée — {EMAIL}'\n"
            "        (remplace {EMAIL} par l'adresse email exacte)\n"
            "      message = "
            "'⚠️ Alerte MailFlow\\n\\n"
            "Nouvelle demande reçue de :\\n"
            "  📧 {EMAIL}\\n"
            "  👤 {PRENOM} {NOM}\\n\\n"
            "Cette personne a déjà reçu le Memento (ligne {ROW}, Statut = Envoyé).\\n"
            "La colonne O a été mise à jour : \\'Envoyer à nouveau ?\\'\\n\\n"
            "✅ Actions disponibles :\\n"
            "→ Renvoyer le Memento :\\n"
            "   1. Ouvrir le Google Sheet\\n"
            "   2. Aller à la ligne {ROW}\\n"
            "   3. Modifier colonne O : \\'Envoyer à nouveau ?\\' → \\'Oui\\'\\n"
            "   4. L\\'expéditeur enverra dans les 7 minutes\\n"
            "→ Ne pas renvoyer : laisser la colonne O sans modification\\n\\n"
            "---\\nMessage automatique — Agent MailFlow'\n"
            "        (remplace {EMAIL}, {PRENOM}, {NOM}, {ROW} par les vraies valeurs)\n\n"
            "ÉTAPE 4 : Indique le nombre d'insertions, doublons et redondances."
        ),
        expected_output=(
            "Texte simple EN FRANÇAIS indiquant : nombre d'emails traités, "
            "nombre d'insertions, nombre de doublons ignorés, nombre de redondances signalées."
        ),
        agent=agent,
    )

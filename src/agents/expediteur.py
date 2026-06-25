"""
Agent expediteur.

Rôle : surveiller le Google Sheet toutes les 7 minutes et traiter deux types
d'envois :

  Type 'premier_envoi' — Approuver=OUI + Statut='En attente' :
      → Envoi email avec lien de téléchargement du Memento
      → Statut → 'Envoyé'
      → Q (Nb envois) + 1

  Type 'renvoi' — Approuver=OUI + Statut='Envoyé' + O='Oui' :
      → Renvoi email (l'opérateur a approuvé manuellement via colonne O)
      → O remis à vide (évite boucle infinie)
      → Q (Nb envois) + 1
      → Statut reste 'Envoyé'

Flux global :
    SheetReadPendingTool → DriveReadMessageTool → SendMailTool →
    SheetUpdateStatusTool (premier_envoi) | SheetClearRedondanceTool (renvoi) →
    SheetIncrementEnvoisTool (tous les cas)
"""

from crewai import Agent, Task

from config.llm import get_llm
from tools.drive_tool import DriveReadMessageTool
from tools.send_mail_tool import SendMailTool
from tools.sheets_tool import (
    SheetClearRedondanceTool,
    SheetIncrementEnvoisTool,
    SheetReadPendingTool,
    SheetUpdateStatusTool,
)


def build_expediteur_agent() -> Agent:
    """
    Instancie l'agent CrewAI chargé de l'envoi des emails Memento.

    Outils disponibles :
      - SheetReadPendingTool     : lit les lignes éligibles (2 types)
      - DriveReadMessageTool     : exporte le Google Doc ContenuMessage en HTML
      - SendMailTool             : envoie l'email via Microsoft Graph API
      - SheetUpdateStatusTool    : passe Statut → 'Envoyé' (premier envoi)
      - SheetClearRedondanceTool : vide O après un renvoi (évite boucle)
      - SheetIncrementEnvoisTool : incrémente Q après chaque envoi

    Returns:
        Agent: instance configurée et prête à recevoir une tâche.
    """
    return Agent(
        role="Expéditeur Email",
        goal=(
            "Consulter le Google Sheet, envoyer l'email avec le lien de "
            "téléchargement du Memento pour chaque demande approuvée, "
            "gérer les premiers envois et les renvois approuvés, "
            "et maintenir le compteur d'envois à jour."
        ),
        backstory=(
            "Tu es un assistant d'envoi de documents. Tu traites deux types "
            "de demandes : les premières demandes (Statut=En attente) et les "
            "renvois approuvés par l'opérateur (Statut=Envoyé + O=Oui). "
            "Tu ne renvoies jamais deux fois sans autorisation explicite. "
            "Après chaque envoi tu mets à jour le compteur et tu nettoies "
            "les flags pour éviter tout traitement en boucle."
        ),
        tools=[
            SheetReadPendingTool(),
            DriveReadMessageTool(),
            SendMailTool(),
            SheetUpdateStatusTool(),
            SheetClearRedondanceTool(),
            SheetIncrementEnvoisTool(),
        ],
        llm=get_llm(),
        verbose=True,
        allow_delegation=False,
    )


def build_expediteur_task(agent: Agent) -> Task:
    """
    Construit la tâche de l'agent expediteur avec la logique d'envoi à deux niveaux.

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
            "ÉTAPE 1 : Appelle l'outil 'sheet_read_pending_rows'.\n"
            "  - Si la liste est vide : termine et indique 'Rien à envoyer'.\n"
            "  - Sinon : continue.\n\n"
            "ÉTAPE 2 : Appelle 'drive_read_contenu_message' une seule fois. "
            "Mémorise l'objet (champ 'objet') et le corps HTML (champ 'corps_html').\n\n"
            "ÉTAPE 3 : Pour chaque ligne retournée par l'étape 1 :\n"
            "  a. Appelle 'send_email_via_graph' avec : "
            "to_email=email de la ligne, subject=objet mémorisé, body_html=corps_html mémorisé.\n"
            "  b. Si send_type='premier_envoi' : appelle 'sheet_update_status_envoye' "
            "avec le row_index exact de la ligne.\n"
            "  c. Si send_type='renvoi' : appelle 'sheet_clear_redondance' "
            "avec le row_index exact de la ligne.\n"
            "  d. Dans tous les cas : appelle 'sheet_increment_envois' "
            "avec le row_index exact de la ligne.\n\n"
            "ÉTAPE 4 : Indique le nombre total d'emails envoyés."
        ),
        expected_output=(
            "Texte simple indiquant le nombre d'emails envoyés "
            "et la liste des destinataires traités."
        ),
        agent=agent,
    )

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
            "1. Utilise 'sheet_read_pending_rows' pour obtenir la liste des "
            "lignes à traiter. Chaque ligne a un champ 'send_type' :\n"
            "   - 'premier_envoi' : première fois que cette personne reçoit le Memento\n"
            "   - 'renvoi'        : l'opérateur a approuvé un renvoi (O=Oui)\n\n"
            "2. Si la liste est vide, termine et indique qu'il n'y a rien à envoyer.\n\n"
            "3. Utilise 'drive_read_contenu_message' une seule fois pour récupérer "
            "l'objet et le corps HTML (lien de téléchargement du Memento inclus). "
            "Le contenu est identique pour tous les destinataires.\n\n"
            "4. Pour chaque ligne, exécute la séquence suivante :\n\n"
            "   a. Utilise 'send_email_via_graph' pour envoyer l'email.\n\n"
            "   b. Si send_type = 'premier_envoi' :\n"
            "      → Utilise 'sheet_update_status_envoye' (Statut → 'Envoyé')\n\n"
            "   c. Si send_type = 'renvoi' :\n"
            "      → Utilise 'sheet_clear_redondance' (O → vide) pour éviter "
            "qu'un nouveau renvoi soit déclenché au prochain cycle.\n\n"
            "   d. Dans TOUS les cas :\n"
            "      → Utilise 'sheet_increment_envois' (Q + 1)\n\n"
            "5. Rapporte le nombre total d'emails envoyés, en distinguant "
            "premiers envois et renvois."
        ),
        expected_output=(
            "Un résumé indiquant le nombre de premiers envois et de renvois "
            "effectués, la liste des destinataires traités, et la confirmation "
            "que les statuts et compteurs ont été mis à jour dans le Google Sheet."
        ),
        agent=agent,
    )

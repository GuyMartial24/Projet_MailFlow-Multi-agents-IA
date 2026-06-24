"""
Agent expediteur.

Rôle : surveiller le Google Sheet toutes les 7 minutes, identifier les demandes
approuvées (Approuver envoi = OUI et Statut = En attente), envoyer l'email avec
le lien de téléchargement du Memento, puis mettre à jour le statut à 'Envoyé'.

Flux :
    Google Sheet → filtre OUI + En attente → lecture ContenuMessage (Google Doc)
    → envoi email HTML (Graph API) → mise à jour statut
"""

from crewai import Agent, Task

from tools.drive_tool import DriveReadMessageTool
from tools.send_mail_tool import SendMailTool
from tools.sheets_tool import SheetReadPendingTool, SheetUpdateStatusTool


def build_expediteur_agent() -> Agent:
    """
    Instancie l'agent CrewAI chargé de l'envoi des emails Memento.

    L'agent utilise quatre outils :
      - SheetReadPendingTool  : lit les lignes approuvées du Google Sheet
      - DriveReadMessageTool  : exporte le Google Doc ContenuMessage en HTML
      - SendMailTool          : envoie l'email via Microsoft Graph API
      - SheetUpdateStatusTool : met à jour le statut de la ligne à 'Envoyé'

    Returns:
        Agent: instance configurée et prête à recevoir une tâche.
    """
    return Agent(
        role="Expéditeur Email",
        goal=(
            "Consulter le Google Sheet et envoyer automatiquement l'email avec "
            "le lien de téléchargement du Memento à toutes les personnes dont la "
            "colonne 'Approuver envoi' est 'OUI' et le 'Statut' est 'En attente'. "
            "Après chaque envoi réussi, mettre à jour le statut de la ligne à 'Envoyé'."
        ),
        backstory=(
            "Tu es un assistant d'envoi de documents. Tu traites les demandes "
            "validées et tu envoies le lien de téléchargement du Memento aux bonnes "
            "personnes, sans jamais envoyer deux fois à la même personne. "
            "Tu utilises toujours le contenu officiel du fichier ContenuMessage "
            "pour rédiger les emails, en préservant le lien cliquable de téléchargement."
        ),
        tools=[
            SheetReadPendingTool(),
            DriveReadMessageTool(),
            SendMailTool(),
            SheetUpdateStatusTool(),
        ],
        verbose=True,
        allow_delegation=False,
    )


def build_expediteur_task(agent: Agent) -> Task:
    """
    Construit la tâche assignée à l'agent expediteur.

    La tâche décrit le comportement attendu lors de chaque cycle de polling
    du Google Sheet.

    Args:
        agent: instance de l'agent à qui assigner la tâche.

    Returns:
        Task: tâche CrewAI prête à être exécutée.
    """
    return Task(
        description=(
            "1. Utilise 'sheet_read_pending_rows' pour obtenir la liste des demandes "
            "approuvées (Approuver envoi = OUI et Statut = En attente).\n"
            "2. Si la liste est vide, arrête-toi et indique qu'il n'y a rien à envoyer.\n"
            "3. Utilise 'drive_read_contenu_message' pour récupérer l'objet et le corps "
            "HTML du mail avec le lien de téléchargement du Memento inclus. "
            "Cette étape ne doit être faite qu'une seule fois : le contenu est "
            "identique pour tous les destinataires.\n"
            "4. Pour chaque ligne de la liste :\n"
            "   a. Utilise 'send_email_via_graph' pour envoyer l'email.\n"
            "   b. Utilise immédiatement 'sheet_update_status_envoye' avec le "
            "row_index de la ligne pour passer le statut à 'Envoyé'.\n"
            "5. Rapporte le nombre total d'emails envoyés et les adresses traitées."
        ),
        expected_output=(
            "Un résumé indiquant combien d'emails avec le lien de téléchargement "
            "du Memento ont été envoyés avec succès, la liste des destinataires "
            "traités et la confirmation que les statuts ont été mis à jour dans "
            "le Google Sheet."
        ),
        agent=agent,
    )

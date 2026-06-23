"""
Agent expediteur.

Rôle : consulter le Google Sheet, envoyer les emails HTML approuvés
et mettre à jour le statut de chaque ligne traitée.
"""

from crewai import Agent, Task

from tools.sheets_tool import SheetReadPendingTool, SheetUpdateStatusTool
from tools.drive_tool import DriveReadMessageTool
from tools.send_mail_tool import SendMailTool


def build_expediteur_agent() -> Agent:
    return Agent(
        role="Expéditeur Email",
        goal=(
            "Consulter le Google Sheet et envoyer automatiquement le lien du memento "
            "à toutes les personnes dont la colonne 'Approuver envoi' est 'OUI' "
            "et le 'Statut' est 'En attente'. "
            "Après chaque envoi réussi, mettre à jour le statut de la ligne à 'Envoyé'."
        ),
        backstory=(
            "Tu es un assistant d'envoi de documents. Tu traites les demandes validées "
            "par l'équipe et tu envoies le lien de téléchargement du memento aux bonnes "
            "personnes sans jamais envoyer deux fois à la même personne. "
            "Tu utilises toujours le contenu officiel du fichier ContenuMessage "
            "pour rédiger les emails, en préservant le lien cliquable."
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
    return Task(
        description=(
            "1. Utilise 'sheet_read_pending_rows' pour obtenir la liste des demandes "
            "approuvées (Approuver envoi = OUI et Statut = En attente).\n"
            "2. Si la liste est vide, arrête-toi et indique qu'il n'y a rien à envoyer.\n"
            "3. Utilise 'drive_read_contenu_message' pour récupérer l'objet et le corps "
            "HTML du mail, avec le lien de téléchargement cliquable inclus "
            "(à faire une seule fois, le contenu est identique pour tous).\n"
            "4. Pour chaque ligne de la liste :\n"
            "   a. Utilise 'send_email_via_graph' pour envoyer l'email HTML.\n"
            "   b. Utilise 'sheet_update_status_envoye' avec le row_index de la ligne "
            "pour passer le statut à 'Envoyé'.\n"
            "5. Rapporte le nombre total d'emails envoyés et les adresses traitées."
        ),
        expected_output=(
            "Un résumé indiquant combien d'emails ont été envoyés avec succès, "
            "la liste des destinataires traités et la confirmation que les statuts "
            "ont été mis à jour dans le Google Sheet."
        ),
        agent=agent,
    )

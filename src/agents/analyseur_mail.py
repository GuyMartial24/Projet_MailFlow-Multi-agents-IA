"""
Agent analyseur_mail.

Rôle : surveiller la boite Outlook de l'utilisateur toutes les 5 minutes,
détecter les emails de demande de Memento envoyés par WordPress,
et enregistrer automatiquement les informations du demandeur dans Google Sheets.

Flux :
    Outlook (Graph API) → filtrage expéditeur + objet → extraction corps email
    → insertion Google Sheet (Statut = En attente)
"""

from crewai import Agent, Task

from tools.outlook_tool import OutlookFetchTool
from tools.sheets_tool import SheetAppendTool


def build_analyseur_mail_agent() -> Agent:
    """
    Instancie l'agent CrewAI chargé de la surveillance de la boite Outlook.

    L'agent utilise deux outils :
      - OutlookFetchTool : récupère les nouveaux emails filtrés depuis la dernière exécution
      - SheetAppendTool  : insère une ligne dans le Google Sheet pour chaque demande détectée

    Returns:
        Agent: instance configurée et prête à recevoir une tâche.
    """
    return Agent(
        role="Analyste Email",
        goal=(
            "Surveiller la boite Outlook de l'utilisateur et détecter les nouveaux "
            "emails de formulaire@exemple.fr dont l'objet contient une demande de "
            "Memento. Pour chaque email détecté, enregistrer l'adresse email, le "
            "prénom et le NOM du demandeur dans le Google Sheet avec la date et le "
            "statut 'En attente'."
        ),
        backstory=(
            "Tu es un assistant de traitement des demandes d'accès au Memento. "
            "Tu surveilles en continu la boite email de l'utilisateur pour ne laisser "
            "passer aucune demande. Les emails WordPress ont une structure normalisée : "
            "la ligne 'De :' dans le corps contient le nom complet et l'email du "
            "vrai demandeur. Tu extrais ces informations avec précision."
        ),
        tools=[OutlookFetchTool(), SheetAppendTool()],
        verbose=True,
        allow_delegation=False,
    )


def build_analyseur_mail_task(agent: Agent) -> Task:
    """
    Construit la tâche assignée à l'agent analyseur_mail.

    La tâche décrit étape par étape le comportement attendu de l'agent
    lors de chaque cycle de polling.

    Args:
        agent: instance de l'agent à qui assigner la tâche.

    Returns:
        Task: tâche CrewAI prête à être exécutée.
    """
    return Task(
        description=(
            "1. Utilise l'outil 'outlook_fetch_new_emails' pour récupérer les "
            "nouveaux emails depuis la dernière vérification.\n"
            "2. Pour chaque email retourné, utilise l'outil 'sheet_append_row' "
            "pour ajouter une ligne dans le Google Sheet. L'outil remplira "
            "automatiquement : Devis (année en cours), Société (extrait du domaine "
            "email), Contact (Prénom NOM dans une cellule), E-mail, Statut "
            "('En attente') et Date enregistrement.\n"
            "3. Si aucun email n'est trouvé, indique simplement qu'aucun nouveau "
            "message n'a été détecté.\n"
            "4. Rapporte le nombre de lignes ajoutées au total."
        ),
        expected_output=(
            "Un résumé indiquant combien de nouvelles demandes ont été enregistrées "
            "dans le Google Sheet, avec le détail (Contact, E-mail, Société) "
            "pour chaque entrée."
        ),
        agent=agent,
    )

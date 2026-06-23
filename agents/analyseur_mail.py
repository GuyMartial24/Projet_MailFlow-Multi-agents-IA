"""
Agent analyseur_mail.

Rôle : surveiller la boite Outlook de l'utilisateur, détecter les demandes de memento
et enregistrer les informations dans le Google Sheet.
"""

from crewai import Agent, Task

from tools.outlook_tool import OutlookFetchTool
from tools.sheets_tool import SheetAppendTool


def build_analyseur_mail_agent() -> Agent:
    return Agent(
        role="Analyste Email",
        goal=(
            "Surveiller la boite Outlook de l'utilisateur et détecter les nouveaux emails "
            "de formulaire@exemple.fr dont l'objet contient une demande de memento. "
            "Pour chaque email détecté, enregistrer l'adresse email, le prénom et le nom "
            "du demandeur dans le Google Sheet avec la date et le statut 'En attente'."
        ),
        backstory=(
            "Tu es un assistant de traitement des demandes d'accès au memento. "
            "Tu surveilles en continu la boite email de l'utilisateur pour ne laisser passer "
            "aucune demande. Tu extrais les informations de contact avec précision "
            "en choisissant toujours la version la plus complète entre le formulaire "
            "et l'adresse email de l'expéditeur."
        ),
        tools=[OutlookFetchTool(), SheetAppendTool()],
        verbose=True,
        allow_delegation=False,
    )


def build_analyseur_mail_task(agent: Agent) -> Task:
    return Task(
        description=(
            "1. Utilise l'outil 'outlook_fetch_new_emails' pour récupérer les nouveaux "
            "emails depuis la dernière vérification.\n"
            "2. Pour chaque email retourné, utilise l'outil 'sheet_append_row' pour "
            "ajouter une ligne dans le Google Sheet avec l'email, le prénom et le nom.\n"
            "3. Si aucun email n'est trouvé, indique simplement qu'aucun nouveau message "
            "n'a été détecté.\n"
            "4. Rapporte le nombre de lignes ajoutées au total."
        ),
        expected_output=(
            "Un résumé indiquant combien de nouvelles demandes ont été enregistrées "
            "dans le Google Sheet, avec le détail (prénom, nom, email) pour chaque entrée."
        ),
        agent=agent,
    )

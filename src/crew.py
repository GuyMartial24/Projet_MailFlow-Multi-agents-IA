"""
Définition des deux Crews CrewAI indépendants.

Chaque Crew encapsule un agent et sa tâche associée.
Les deux crews sont instanciés et exécutés indépendamment par main.py
dans des threads séparés :
  - AnalyseurCrew : surveillance Outlook → écriture Google Sheet
  - ExpediteurCrew : lecture Google Sheet → envoi email avec lien Memento
"""

from crewai import Crew, Process

from agents.analyseur_mail import (
    build_analyseur_mail_agent,
    build_analyseur_mail_task,
)
from agents.expediteur import (
    build_expediteur_agent,
    build_expediteur_task,
)


def build_analyseur_crew() -> Crew:
    """
    Construit le Crew de l'agent analyseur_mail.

    L'agent surveille la boite Outlook, filtre les demandes de Memento
    et enregistre les informations des demandeurs dans Google Sheets.

    Returns:
        Crew: instance prête à être exécutée via kickoff().
    """
    agent = build_analyseur_mail_agent()
    task = build_analyseur_mail_task(agent)
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


def build_expediteur_crew() -> Crew:
    """
    Construit le Crew de l'agent expediteur.

    L'agent lit le Google Sheet, envoie l'email avec le lien de
    téléchargement du Memento pour chaque demande approuvée,
    puis met à jour le statut de la ligne à 'Envoyé'.

    Returns:
        Crew: instance prête à être exécutée via kickoff().
    """
    agent = build_expediteur_agent()
    task = build_expediteur_task(agent)
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )

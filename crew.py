"""
Définition des deux Crews CrewAI indépendants.

- AnalyseurCrew : agent analyseur_mail (polling Outlook → Google Sheet)
- ExpediteurCrew : agent expediteur (polling Google Sheet → envoi email)

Les deux crews tournent en parallèle avec leurs propres intervalles de polling
gérés dans main.py.
"""

from crewai import Crew, Process

from agents.analyseur_mail import build_analyseur_mail_agent, build_analyseur_mail_task
from agents.expediteur import build_expediteur_agent, build_expediteur_task


def build_analyseur_crew() -> Crew:
    agent = build_analyseur_mail_agent()
    task  = build_analyseur_mail_task(agent)
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


def build_expediteur_crew() -> Crew:
    agent = build_expediteur_agent()
    task  = build_expediteur_task(agent)
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )

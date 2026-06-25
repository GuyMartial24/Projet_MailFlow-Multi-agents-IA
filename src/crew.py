"""
Orchestration des deux agents MailFlow.

- AnalyseurCrew  : CrewAI + qwen2.5:14b (logique conditionnelle Cas 1/2/3)
- ExpediteurRunner : Python pur, sans LLM (logique deterministe, 0 hallucination)
"""

from crewai import Crew, Process

from agents.analyseur_mail import (
    build_analyseur_mail_agent,
    build_analyseur_mail_task,
)
from agents.expediteur import ExpéditeurRunner


def build_analyseur_crew() -> Crew:
    """
    Construit le Crew CrewAI de l'agent analyseur_mail.

    Utilise qwen2.5:14b pour detecter les demandes, gerer les doublons
    et les redondances avec la logique conditionnelle Cas 1/2/3.

    Returns:
        Crew: instance prete a etre executee via kickoff().
    """
    agent = build_analyseur_mail_agent()
    task = build_analyseur_mail_task(agent)
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


def build_expediteur_crew() -> ExpéditeurRunner:
    """
    Retourne un ExpéditeurRunner (orchestration Python pure, sans LLM).

    Remplace l'ancien Crew CrewAI qui hallusinait le contenu du message.
    Compatible avec main.py via la methode kickoff().

    Returns:
        ExpéditeurRunner: instance prete a etre executee via kickoff().
    """
    return ExpéditeurRunner()

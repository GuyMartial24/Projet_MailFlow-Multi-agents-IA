"""
Configuration du LLM local (Ollama sur VPS).

Fournit une factory get_llm() utilisée par tous les agents CrewAI.
Le modèle est servi par Ollama à http://localhost:11434 sur le VPS.

CrewAI utilise LiteLLM en interne, qui supporte Ollama nativement
via le préfixe 'ollama/' dans le nom du modèle.

Variables d'environnement (.env) :
    LLM_BASE_URL : URL du serveur Ollama (défaut : http://localhost:11434)
    LLM_MODEL    : Modèle à utiliser  (défaut : ollama/llama3.1)
"""

from crewai import LLM

from config import settings


def get_llm() -> LLM:
    """
    Instancie et retourne le LLM local configuré pour les agents CrewAI.

    Le modèle Ollama est accessible uniquement en local sur le VPS
    (http://localhost:11434), ce qui garantit qu'aucune donnée n'est
    envoyée vers un service d'inférence externe.

    Returns:
        LLM: instance CrewAI configurée avec le modèle Ollama local.
    """
    return LLM(
        model=settings.LLM_MODEL,        # ex. 'ollama/llama3.1'
        base_url=settings.LLM_BASE_URL,  # ex. 'http://localhost:11434'
    )

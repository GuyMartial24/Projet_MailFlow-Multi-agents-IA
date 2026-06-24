"""
Point d'entrée — MailFlow.

Lance les deux crews CrewAI en parallèle dans des threads dédiés :
  - analyseur_mail : polling boite Outlook toutes les ANALYSEUR_MAIL_INTERVAL secondes
  - expediteur     : polling Google Sheet toutes les EXPEDITEUR_INTERVAL secondes

Usage :
    python main.py
"""

import sys
import time
import logging
import threading
from pathlib import Path
from typing import Callable

# Résolution des imports internes depuis src/
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import settings                                   # noqa: E402
from config.settings import validate_config                   # noqa: E402
from crew import build_analyseur_crew, build_expediteur_crew  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration du logger global
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s — %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Boucle de polling générique
# ---------------------------------------------------------------------------

def _run_crew_loop(
    name: str,
    build_fn: Callable,
    interval: int,
) -> None:
    """
    Boucle infinie qui instancie et exécute un Crew CrewAI à intervalle régulier.

    Args:
        name:      Nom de l'agent (utilisé dans les logs).
        build_fn:  Fonction factory qui construit et retourne un objet Crew.
        interval:  Délai en secondes entre deux cycles.
    """
    log.info(f"{name} démarré — intervalle : {interval}s")
    while True:
        try:
            log.info(f"{name} — lancement d'un cycle")
            crew = build_fn()
            crew.kickoff()
        except Exception as exc:
            # On logue l'erreur mais on ne stoppe pas la boucle
            log.error(
                f"{name} — erreur lors du cycle : {exc}",
                exc_info=True,
            )

        log.info(f"{name} — prochain cycle dans {interval}s")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Valide la configuration, puis démarre les deux agents en threads démons.

    Lève SystemExit(1) si des variables d'environnement obligatoires
    sont manquantes dans le fichier .env.
    """
    # Vérification anticipée de la configuration avant tout démarrage
    missing = validate_config()
    if missing:
        log.error(
            "Variables de configuration manquantes dans .env :\n"
            + "\n".join(f"  • {v}" for v in missing)
        )
        raise SystemExit(1)

    # Définition des deux threads de polling
    threads = [
        threading.Thread(
            target=_run_crew_loop,
            args=(
                "analyseur_mail",
                build_analyseur_crew,
                settings.ANALYSEUR_MAIL_INTERVAL,
            ),
            name="analyseur_mail",
            daemon=True,  # Arrêt automatique à la fin du processus principal
        ),
        threading.Thread(
            target=_run_crew_loop,
            args=(
                "expediteur",
                build_expediteur_crew,
                settings.EXPEDITEUR_INTERVAL,
            ),
            name="expediteur",
            daemon=True,
        ),
    ]

    for t in threads:
        t.start()

    log.info("MailFlow actif. Ctrl+C pour arrêter.")
    try:
        # Maintien du thread principal en vie
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Arrêt demandé — fin du programme.")


if __name__ == "__main__":
    main()

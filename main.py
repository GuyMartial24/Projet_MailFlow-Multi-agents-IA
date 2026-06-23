"""
Point d'entrée — MailFlow.

Lance les deux crews en parallèle (threads séparés) avec leurs propres intervalles :
- analyseur_mail : toutes les ANALYSEUR_MAIL_INTERVAL secondes (défaut 5 min)
- expediteur     : toutes les EXPEDITEUR_INTERVAL secondes (défaut 7 min)
"""

import sys
import time
import threading
import logging
from pathlib import Path

# Ajoute src/ au chemin Python pour résoudre les imports internes
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import settings
from config.settings import validate_config
from crew import build_analyseur_crew, build_expediteur_crew

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s — %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger(__name__)


def _run_crew_loop(name: str, build_fn, interval: int) -> None:
    """Boucle infinie : exécute le crew puis attend l'intervalle."""
    log.info(f"{name} démarré — intervalle : {interval}s")
    while True:
        try:
            log.info(f"{name} — lancement d'un cycle")
            crew = build_fn()
            crew.kickoff()
        except Exception as exc:
            log.error(f"{name} — erreur lors du cycle : {exc}", exc_info=True)

        log.info(f"{name} — prochain cycle dans {interval}s")
        time.sleep(interval)


def main() -> None:
    missing = validate_config()
    if missing:
        log.error(
            "Variables de configuration manquantes dans .env :\n"
            + "\n".join(f"  • {v}" for v in missing)
        )
        raise SystemExit(1)

    threads = [
        threading.Thread(
            target=_run_crew_loop,
            args=("analyseur_mail", build_analyseur_crew, settings.ANALYSEUR_MAIL_INTERVAL),
            name="analyseur_mail",
            daemon=True,
        ),
        threading.Thread(
            target=_run_crew_loop,
            args=("expediteur", build_expediteur_crew, settings.EXPEDITEUR_INTERVAL),
            name="expediteur",
            daemon=True,
        ),
    ]

    for t in threads:
        t.start()

    log.info("MailFlow actif. Ctrl+C pour arrêter.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Arrêt demandé — fin du programme.")


if __name__ == "__main__":
    main()

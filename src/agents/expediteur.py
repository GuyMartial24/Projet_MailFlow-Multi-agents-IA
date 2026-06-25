"""
Agent expediteur — orchestration Python pure (sans LLM).

Remplace l'ancien agent CrewAI qui hallusinait le contenu du message.
La logique est 100% deterministe : Python appelle directement les outils
dans le bon ordre, sans passer par un LLM.

Cycle :
  1. SheetReadPendingTool  → lignes approuvees (Approuver=OUI + Statut=En attente
                             ou Approuver=OUI + Statut=Envoye + O=Oui)
  2. DriveReadMessageTool  → objet + corps HTML depuis ContenuMessage (1 seul appel)
  3. Pour chaque ligne :
       a. SendMailTool              → envoi email HTML avec lien de telechargement
       b. SheetUpdateStatusTool     → Statut -> Envoye  (premier_envoi)
          SheetClearRedondanceTool  → O -> vide         (renvoi)
       c. SheetIncrementEnvoisTool  → Q + 1
"""

import logging

log = logging.getLogger(__name__)

from tools.drive_tool import DriveReadMessageTool
from tools.send_mail_tool import SendMailTool
from tools.sheets_tool import (
    SheetClearRedondanceTool,
    SheetIncrementEnvoisTool,
    SheetReadPendingTool,
    SheetUpdateStatusTool,
)


# ---------------------------------------------------------------------------
# Logique du cycle (Python pur)
# ---------------------------------------------------------------------------

def run_expediteur_cycle() -> None:
    """
    Execute un cycle complet de l'expediteur sans aucun LLM.

    Toutes les decisions sont prises par le code Python, eliminant
    tout risque d'hallucination sur l'objet ou le corps du message.
    """
    # ETAPE 1 : Lire les lignes a traiter (premier envoi + renvois approuves)
    pending = SheetReadPendingTool()._run()

    if not pending:
        log.info("Expediteur : rien a envoyer — aucune ligne approuvee")
        return

    log.info(f"Expediteur : {len(pending)} ligne(s) a traiter")

    # ETAPE 2 : Recuperer le contenu du message depuis Google Drive (une seule fois)
    try:
        message = DriveReadMessageTool()._run()
        objet = message.get("objet", "").strip()
        corps_html = message.get("corps_html", "").strip()
    except Exception as exc:
        log.error(f"Expediteur : impossible de lire ContenuMessage — {exc}")
        return

    if not objet:
        log.error("Expediteur : objet vide dans ContenuMessage — envoi annule")
        return
    if not corps_html:
        log.error("Expediteur : corps_html vide dans ContenuMessage — envoi annule")
        return

    log.info(f"Expediteur : objet recupere = '{objet}'")

    # ETAPE 3 : Traiter chaque ligne
    sent = 0
    errors = 0

    send_tool     = SendMailTool()
    status_tool   = SheetUpdateStatusTool()
    clear_tool    = SheetClearRedondanceTool()
    increment_tool = SheetIncrementEnvoisTool()

    for row in pending:
        email      = row.get("email", "")
        contact    = row.get("contact", "")
        row_index  = row.get("row_index")
        send_type  = row.get("send_type", "premier_envoi")

        try:
            # a. Envoi de l'email avec le vrai contenu de ContenuMessage
            send_tool._run(
                to_email=email,
                subject=objet,
                body_html=corps_html,
            )

            # b. Mise a jour du statut selon le type d'envoi
            if send_type == "premier_envoi":
                status_tool._run(row_index=row_index)
            elif send_type == "renvoi":
                # Vider O pour eviter un renvoi en boucle au prochain cycle
                clear_tool._run(row_index=row_index)

            # c. Incrementer le compteur Q (tous les cas)
            increment_tool._run(row_index=row_index)

            log.info(
                f"Expediteur : email envoye a {contact} <{email}> "
                f"[{send_type}] (ligne {row_index})"
            )
            sent += 1

        except Exception as exc:
            log.error(f"Expediteur : erreur envoi {email} — {exc}")
            errors += 1

    log.info(f"Expediteur : cycle termine — {sent} envoye(s), {errors} erreur(s)")


# ---------------------------------------------------------------------------
# Wrapper compatible avec main.py (interface kickoff())
# ---------------------------------------------------------------------------

class ExpéditeurRunner:
    """
    Objet compatible avec l'interface Crew CrewAI (methode kickoff).
    Permet a main.py d'utiliser ce runner sans modification.
    """

    def kickoff(self) -> None:
        """Appele par main.py a chaque cycle de polling."""
        run_expediteur_cycle()

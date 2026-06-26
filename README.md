# MailFlow — Système Multi-Agents IA

> **Auteur :** Martial GADJEU | Data Engineer & AI

---

## Contexte

L'organisation reçoit régulièrement des demandes d'accès au Memento via un formulaire WordPress.
Le traitement de ces demandes était entièrement manuel : consultation des emails, copie des
coordonnées, envoi individuel du document, mise à jour du suivi.
Ce processus représentait une perte de **30 min à 1h par semaine**.

Ce projet automatise l'intégralité de cette chaîne tout en conservant une validation humaine
avant chaque envoi.

---

## Problématique

La solution devait répondre à deux contraintes fortes :

- **Confidentialité** : les données des demandeurs (nom, email) ne transitent par aucun
  service cloud tiers. La solution est hébergée sur un **VPS privé sous Linux (Oracle)**,
  y compris les agents IA et le LLM. Aucune donnée n'est envoyée à une API d'inférence externe.

- **Technologie & granularité** : le système combine **CrewAI** (agent analyseur) et
  **Python pur** (agent expéditeur). Contrairement aux solutions No-code / Low-code (Make,
  Zapier, n8n…), une implémentation en code pur offre un niveau de granularité bien supérieur :
  contrôle fin des filtres email (logique AND/OR), extraction multi-sources du demandeur,
  gestion des doublons et redondances, fetch incrémental sans doublon, parsing ciblé d'un
  Google Doc natif, envoi HTML avec lien de téléchargement, et mise à jour atomique du statut
  ligne par ligne. Chaque comportement est explicitement maîtrisé,
  sans dépendre des limites ou des boîtes noires d'un outil visuel.

---

## Solution

Système automatisé pour traiter les demandes d'accès au Memento.
Deux agents tournent en parallèle et en continu sur le VPS.

### Agent `analyseur_mail` — Surveillance de la boite mail (CrewAI + qwen2.5:14b)

Interroge la boite Outlook **toutes les 5 minutes** via Microsoft Graph API.
Fetch incrémental : seuls les emails reçus depuis la dernière exécution sont traités.

Pour chaque email détecté, l'agent applique une **logique à 3 cas** :

| Cas | Condition | Action |
|-----|-----------|--------|
| 1 — Nouveau | Email absent du Sheet | Insertion nouvelle ligne (Statut = *En attente*) |
| 2 — Doublon | Email présent + Statut = *En attente* | Notification opérateur |
| 3 — Redondance | Email présent + Approuver = OUI + Statut = *Envoyé* | Marque O = *Envoyer à nouveau ?* + notification |

Les **notifications** (cas 2 et 3) sont envoyées par double canal : log journalctl +
email à la boite de l'opérateur avec les actions disponibles.

### Agent `expediteur` — Surveillance du Google Sheet (Python pur, sans LLM)

Lit le Google Sheet **toutes les 7 minutes**. Orchestration **100% Python** — aucun LLM
impliqué, éliminant tout risque d'hallucination sur l'objet ou le corps du message.

Deux types d'envoi :
- **Premier envoi** : Approuver = `OUI` + Statut = *En attente*
- **Renvoi** : Approuver = `OUI` + Statut = *Envoyé* + O = `Oui` (approuvé manuellement)

Après chaque envoi : Statut mis à jour, colonne O vidée (anti-boucle), compteur Q incrémenté.

---

## Prérequis

- Python 3.11+
- Un compte Azure avec une application enregistrée (Microsoft Graph API)
- Un compte de service Google (Google Cloud Console)
- Accès au Google Sheet et au Google Doc ContenuMessage
- Une boite Outlook avec accès Microsoft Graph API configuré
- **Ollama** installé sur le VPS avec le modèle **qwen2.5:14b** (`ollama pull qwen2.5:14b`)

---

## Installation

```bash
# 1. Cloner le repo
git clone https://github.com/GuyMartial24/Projet_MailFlow-Multi-agents-IA.git
cd Projet_MailFlow-Multi-agents-IA

# 2. Créer un environnement virtuel
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# 3. Installer les dépendances
pip install -r requirements.txt
```

---

## Configuration

### 1. Fichier `.env`

Copier `.env.example` en `.env` et renseigner les valeurs :

```bash
copy .env.example .env
```

### 2. Compte de service Google

Déposer le fichier JSON du compte de service dans :
```
src/config/credentials/google_service_account.json
```

Partager le Google Sheet et le Google Doc ContenuMessage avec l'email du compte de service
(champ `client_email` dans le JSON).

---

## Lancement

```bash
python main.py
```

Le programme démarre les deux agents en parallèle. Arrêt propre avec `Ctrl+C`.

En production sur le VPS, le service systemd gère le démarrage automatique :
```bash
sudo systemctl start mailflow
sudo journalctl -u mailflow -f   # logs en temps réel
```

---

## Structure du projet

```
MailFlow/
├── .env                          # Credentials et IDs (non versionné)
├── .env.example                  # Template de configuration
├── .gitignore
├── requirements.txt
├── main.py                       # Point d'entrée — boucles de polling
├── batch_migration.py            # Script one-shot import dossier Outlook → Sheet
├── docs/
│   ├── logique_projet_MailFlow.md
│   └── README_REMPLACEMENT_FICHIER_MEMENTO.txt
├── deploy/
│   ├── mailflow.service          # Service systemd VPS
│   └── INSTALL_VPS.md            # Guide de déploiement
├── src/
│   ├── crew.py                   # analyseur_mail (Crew) + expediteur (Python pur)
│   ├── agents/
│   │   ├── analyseur_mail.py     # Agent CrewAI : surveillance emails, 3 cas
│   │   └── expediteur.py         # Python pur : envoi Memento, anti-hallucination
│   ├── tools/
│   │   ├── outlook_tool.py       # Fetch emails Outlook (Graph API)
│   │   ├── send_mail_tool.py     # Envoi email HTML (Graph API)
│   │   ├── sheets_tool.py        # Lecture/écriture Google Sheets (7 outils)
│   │   ├── drive_tool.py         # Export Google Doc + parsing HTML
│   │   └── notify_tool.py        # Notifications opérateur (log + email)
│   └── config/
│       ├── settings.py           # Lecture centralisée du .env
│       ├── llm.py                # Factory LLM Ollama (qwen2.5:14b)
│       └── credentials/
│           └── google_service_account.json  # À déposer ici (non versionné)
└── state/
    └── last_check_outlook.json   # Timestamp incrémental (auto-créé, non versionné)
```

---

## Fonctionnement complet

| Étape | Agent | Action |
|-------|-------|--------|
| 1 | `analyseur_mail` | Fetch emails `formulaire@exemple.fr` depuis la dernière exécution |
| 2a | `analyseur_mail` | **Nouveau** : insère dans le Sheet (Dévis, Société, Contact, E-mail, Statut=*En attente*) |
| 2b | `analyseur_mail` | **Doublon** : notifie l'opérateur par email + log |
| 2c | `analyseur_mail` | **Redondance** : marque O=*Envoyer à nouveau ?* + notifie |
| 3 | Humain | Met **L = `OUI`** dans le Sheet pour approuver l'envoi |
| 3b | Humain (renvoi) | Met **O = `Oui`** pour approuver un renvoi à un contact déjà servi |
| 4 | `expediteur` | Lit ContenuMessage (Google Doc), envoie l'email avec le lien du Memento |
| 5 | `expediteur` | Statut → *Envoyé*, Q + 1 (compteur d'envois) |
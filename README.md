# MailFlow — Système Multi-Agents IA

> **Auteur :** Martial GADJEU | Data Engineer & AI

---

## Contexte

L'organisation reçoit régulièrement des demandes d'accès au Memento via un formulaire WordPress.
Le traitement de ces demandes était entièrement manuel : consultation des emails, copie des
coordonnées, envoi individuel du document, mise à jour du suivi.
Ce processus représentait une perte de **30 à 45 minutes par semaine**.

Ce projet automatise l'intégralité de cette chaîne tout en conservant une validation humaine
avant chaque envoi.

---

## Problématique

La solution devait répondre à deux contraintes fortes :

- **Confidentialité** : les données des demandeurs (nom, email) ne transitent par aucun
  service cloud tiers. Tout s'exécute en local sur la machine de l'opérateur, y compris
  les agents IA. Aucune donnée n'est envoyée à une API d'inférence externe.

- **Technologie** : le système est construit avec **CrewAI**, framework Python de
  multi-agents IA, qui orchestre les deux agents de manière autonome et parallèle.

---

## Solution

Système automatisé basé sur **CrewAI** pour traiter les demandes d'accès au Memento.

Deux agents IA tournent en parallèle :
- **`analyseur_mail`** : surveille la boite Outlook de l'utilisateur et enregistre les demandes dans Google Sheets
- **`expediteur`** : envoie automatiquement le lien du Memento aux demandes approuvées

---

## Prérequis

- Python 3.11+
- Un compte Azure avec une application enregistrée (Microsoft Graph API)
- Un compte de service Google (Google Cloud Console)
- Accès au Google Sheet et au Google Doc ContenuMessage
- La boite Outlook `utilisateur@exemple.fr`

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

Copier `.env.example` en `.env` et renseigner les valeurs manquantes :

```bash
copy .env.example .env
```

Les credentials Microsoft Graph API et les IDs Google sont déjà documentés dans `.env.example`.

### 2. Compte de service Google

Déposer le fichier `google_service_account.json` dans :
```
src/config/credentials/google_service_account.json
```

Partager ensuite le Google Sheet et le Google Doc ContenuMessage avec l'email du compte de service (visible dans le JSON, champ `client_email`).

---

## Lancement

```bash
python main.py
```

Le programme démarre les deux agents en parallèle et affiche les logs en temps réel.
Arrêt propre avec `Ctrl+C`.

---

## Structure du projet

```
MailFlow/
├── .env                          # Credentials et IDs (non versionné)
├── .env.example                  # Template de configuration
├── .gitignore
├── requirements.txt
├── main.py                       # Point d'entrée — boucles de polling
├── docs/
│   ├── logique_projet_MailFlow.md
│   └── README_REMPLACEMENT_FICHIER_MEMENTO.txt
├── src/
│   ├── crew.py                   # Définition des deux Crews CrewAI
│   ├── agents/
│   │   ├── analyseur_mail.py     # Agent 1 : surveillance emails
│   │   └── expediteur.py         # Agent 2 : envoi Memento
│   ├── tools/
│   │   ├── outlook_tool.py       # Fetch emails Outlook (Graph API)
│   │   ├── send_mail_tool.py     # Envoi email HTML (Graph API)
│   │   ├── sheets_tool.py        # Lecture/écriture Google Sheets
│   │   └── drive_tool.py         # Export Google Doc + parsing
│   └── config/
│       ├── settings.py           # Lecture centralisée du .env
│       └── credentials/
│           └── google_service_account.json  # À déposer ici (non versionné)
└── state/
    └── last_check_outlook.json   # Timestamp incrémental (auto-créé)
```

---

## Fonctionnement

| Étape | Agent | Action |
|-------|-------|--------|
| 1 | `analyseur_mail` | Détecte les emails de `formulaire@exemple.fr` avec objet "demande memento" |
| 2 | `analyseur_mail` | Enregistre Email, Nom, Prénom, Date dans Google Sheets (Statut = *En attente*) |
| 3 | Humain | Remplit la colonne **Approuver envoi ?** avec `OUI` dans le Google Sheet |
| 4 | `expediteur` | Détecte les lignes `OUI` + `En attente`, envoie l'email HTML avec lien Memento |
| 5 | `expediteur` | Met à jour le Statut → **Envoyé** |

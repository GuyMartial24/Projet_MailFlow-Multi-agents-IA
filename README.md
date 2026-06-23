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
  y compris les agents IA. Aucune donnée n'est envoyée à une API d'inférence externe.

- **Technologie & granularité** : le système est construit avec **CrewAI**, framework Python de
  multi-agents IA. Contrairement aux solutions No-code / Low-code (Make, Zapier, n8n…),
  une implémentation en code pur offre un niveau de granularité bien supérieur :
  contrôle fin des filtres email (logique AND/OR), extraction ciblée du demandeur
  dans le corps du formulaire WordPress, fetch incrémental sans doublon,
  parsing ciblé d'un Google Doc natif, envoi HTML avec lien cliquable, et mise à jour
  atomique du statut ligne par ligne. Chaque comportement est explicitement maîtrisé,
  sans dépendre des limites ou des boîtes noires d'un outil visuel.

---

## Solution

Système automatisé basé sur **CrewAI** pour traiter les demandes d'accès au Memento.
Deux agents IA tournent en parallèle et en continu sur le VPS.

### Agent `analyseur_mail` — Surveillance de la boite mail

Cet agent interroge la boite Outlook de l'utilisateur **toutes les 5 minutes** via
Microsoft Graph API. À chaque cycle, il récupère uniquement les emails reçus **depuis
sa dernière exécution** grâce à un timestamp horodaté sauvegardé localement
(`state/last_check_outlook.json`). Ce mécanisme de **fetch incrémental** garantit
qu'aucun email n'est traité deux fois.

Chaque email est filtré :
- expéditeur `formulaire@exemple.fr` (notifications WordPress)
- objet contenant une variante de "Demande Mémento"

Pour chaque demande détectée, l'agent extrait l'email, le prénom et le NOM du demandeur
depuis la ligne `De :` dans le corps du formulaire, puis insère une nouvelle ligne dans
le Google Sheet avec le statut `En attente`.

### Agent `expediteur` — Surveillance du Google Sheet

Cet agent lit le Google Sheet **toutes les 7 minutes**. À chaque cycle, il parcourt
toutes les lignes et cible exclusivement celles qui réunissent deux conditions :
- colonne **Approuver envoi ?** = `OUI` (validé manuellement)
- colonne **Statut** = `En attente`

Pour chaque ligne éligible, il récupère le contenu du message depuis le Google Doc
ContenuMessage, envoie l'email HTML avec le lien de téléchargement cliquable,
puis met à jour le statut de la ligne à `Envoyé` — empêchant tout double envoi.

---

## Prérequis

- Python 3.11+
- Un compte Azure avec une application enregistrée (Microsoft Graph API)
- Un compte de service Google (Google Cloud Console)
- Accès au Google Sheet et au Google Doc ContenuMessage
- Une boite Outlook avec accès Microsoft Graph API configuré

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

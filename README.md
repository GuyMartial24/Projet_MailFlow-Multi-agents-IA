# MailFlow — Système Multi-Agents IA

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
config/credentials/google_service_account.json
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
├── crew.py                       # Définition des deux Crews CrewAI
├── config/
│   ├── settings.py               # Lecture centralisée du .env
│   └── credentials/
│       └── google_service_account.json  # À déposer ici (non versionné)
├── tools/
│   ├── outlook_tool.py           # Fetch emails Outlook (Graph API)
│   ├── send_mail_tool.py         # Envoi email HTML (Graph API)
│   ├── sheets_tool.py            # Lecture/écriture Google Sheets
│   └── drive_tool.py             # Export Google Doc + parsing
├── agents/
│   ├── analyseur_mail.py         # Agent 1 : surveillance emails
│   └── expediteur.py             # Agent 2 : envoi Memento
└── state/
    └── last_check_outlook.json   # Timestamp incrémental (auto-créé)
```

---

## Fonctionnement rapide

| Étape | Agent | Action |
|-------|-------|--------|
| 1 | `analyseur_mail` | Détecte les emails de `formulaire@exemple.fr` avec objet "demande memento" |
| 2 | `analyseur_mail` | Enregistre Email, Nom, Prénom, Date dans Google Sheets (Statut = *En attente*) |
| 3 | Humain | Remplit la colonne **Approuver envoi ?** avec `OUI` dans le Google Sheet |
| 4 | `expediteur` | Détecte les lignes `OUI` + `En attente`, envoie l'email HTML avec lien Memento |
| 5 | `expediteur` | Met à jour le Statut → **Envoyé** |

Pour la logique détaillée, voir [logique_projet_MailFlow.md](logique_projet_MailFlow.md).

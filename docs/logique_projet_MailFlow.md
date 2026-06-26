# Logique détaillée — Projet MailFlow

## Contexte

L'organisation utilise un formulaire WordPress pour recueillir les demandes d'accès au Memento.
Chaque soumission de formulaire génère un email automatique envoyé depuis `formulaire@exemple.fr`
vers la boite professionnelle de l'utilisateur (`utilisateur@exemple.fr`).

Le système MailFlow automatise la chaîne de traitement : détection → enregistrement →
approbation manuelle → envoi du lien Memento → confirmation.

La solution est hébergée sur un **VPS privé sous Linux (Oracle)**, ce qui garantit que
les données des demandeurs ne transitent par aucun service cloud tiers.
Le LLM (qwen2.5:14b via Ollama) tourne localement sur le même VPS.

---

## Architecture générale

```
[Formulaire WordPress]
        │  email automatique (formulaire@exemple.fr)
        ▼
[Boite Outlook utilisateur]
        │
        ├── Agent analyseur_mail (CrewAI + qwen2.5:14b, polling 5 min)
        │       │
        │       ├─ Cas 1 : email absent   → insertion Google Sheet
        │       ├─ Cas 2 : doublon        → notification opérateur
        │       └─ Cas 3 : redondance     → O="Envoyer à nouveau ?" + notification
        │
        ▼
[Google Sheet — 17 colonnes A→Q]
        │
        │  approbation manuelle (col L = OUI)
        ▼
Agent expediteur (Python pur, polling 7 min)
        │
        ├─ Premier envoi : Approuver=OUI + Statut=En attente
        └─ Renvoi       : Approuver=OUI + Statut=Envoyé + O=Oui
        │
        ▼
[Email HTML avec lien de téléchargement du Memento]
```

---

## Agent 1 — `analyseur_mail` (CrewAI + qwen2.5:14b)

### Fréquence
Toutes les **5 minutes** (`ANALYSEUR_MAIL_INTERVAL` dans `.env`).

### Technologie
Utilise **CrewAI** avec le modèle **qwen2.5:14b** via **Ollama** (local sur le VPS).
Ollama est accessible sur `http://localhost:11434`.

### Connexion Outlook
Microsoft Graph API, flux *client credentials* (OAuth 2.0 via MSAL) :
- Lecture de la boite via l'endpoint `/users/{email}/messages`
- Corps des emails demandé en **texte brut** (header `Prefer: outlook.body-content-type="text"`)

### Fetch incrémental
À chaque cycle :
1. Lecture de `state/last_check_outlook.json` → timestamp de dernière exécution
2. `now_iso` capturé **après** l'appel API (évite de manquer des emails arrivés pendant le cycle)
3. Filtre OData : `from = "formulaire@exemple.fr" AND receivedDateTime gt {last_check}`
4. Sauvegarde de `now_iso` en fin de cycle

### Filtre des emails
```
expéditeur = "formulaire@exemple.fr"
AND
(objet CONTIENT "demande memento" OR "demande mémento"
 OR "demande d'accès au memento" OR "accès mémento" ...)
```

### Extraction Prénom / NOM — Comparaison multi-sources

Les emails WordPress ont cette structure dans le corps :
```
De : Jean Dupont jean.dupont@gmail.com
Objet : Demande Mémento 2025
Corps du message : ...
```

L'agent extrait depuis **deux sources** et retient la plus complète :

| Source | Méthode |
|--------|---------|
| Ligne `De :` du corps | Regex : tout avant l'email = nom complet |
| Partie locale de l'adresse email | Split par `.` `_` `-`, filtre initiales/chiffres/génériques |

**Règle** : la source avec le plus de mots (prenom + nom) gagne. En cas d'égalité, le corps prime.

**Normalisation** : Prénom en `Title Case`, NOM en `MAJUSCULES`.

### Logique à 3 cas

```
Pour chaque email :
    ↓
  sheet_find_email(email)
    │
    ├─ found=False
    │    → CAS 1 : Nouveau contact
    │    → sheet_append_row(email, prenom, nom)
    │
    ├─ found=True + statut='En attente'
    │    → CAS 2 : Doublon en cours
    │    → notify_operator(Doublon détecté)
    │
    └─ found=True + approuver='OUI' + statut='Envoyé'
         → CAS 3 : Contact déjà servi, nouvelle demande
         → sheet_mark_redondance(row_index) → O='Envoyer à nouveau ?', P=timestamp
         → notify_operator(Redondance détectée)
```

### Notifications opérateur (double canal)

Chaque anomalie déclenche :
1. **Log WARNING** dans journalctl (trace permanente)
2. **Email HTML** à `utilisateur@exemple.fr` (alerte proactive)

**Format Doublon :**
```
Objet : [MailFlow] Doublon détecté — {email}

⚠️ Alerte MailFlow
Nouvelle demande reçue de : 📧 {email} / 👤 {contact}
Cette personne a déjà une demande EN ATTENTE (ligne {row}).

✅ Actions :
→ Ne rien faire : la demande existante sera traitée normalement
→ Vérifier manuellement : Google Sheet > ligne {row}
```

**Format Redondance :**
```
Objet : [MailFlow] Redondance détectée — {email}

⚠️ Alerte MailFlow
Nouvelle demande reçue de : 📧 {email} / 👤 {contact}
Cette personne a déjà reçu le Memento (ligne {row}, Statut = Envoyé).
La colonne O a été mise à jour : 'Envoyer à nouveau ?'

✅ Actions :
→ Renvoyer : Google Sheet > ligne {row} > colonne O → 'Oui'
→ Ne pas renvoyer : laisser la colonne O sans modification
```

### Écriture dans Google Sheets — 17 colonnes A→Q

| Col | Libellé | Rempli par |
|-----|---------|-----------|
| A | Devis | Agent (année en cours) |
| B | Société | Agent (domaine email) |
| C | Contact | Agent (Prénom NOM) |
| D | Tél. | Manuel |
| E | E-mail | Agent |
| F | PME | Manuel |
| G | Visites d'entreprises | Manuel |
| H | Visites de centres de compétences | Manuel |
| I | Autres visites | Manuel |
| J | Téléchargement études | Manuel |
| K | Projet | Manuel |
| L | Approuver envoi ? | **Manuel** (OUI / NON) |
| M | Statut | Agent (En attente / Envoyé) |
| N | Date enregistrement 1ère demande | Agent (jj/mm/aaaa hh:mm) |
| O | Gestion des redondances | Agent → `Envoyer à nouveau ?` / Opérateur → `Oui` |
| P | Dernière date nouvelle demande | Agent (n-ième demande uniquement) |
| Q | Nombre d'envois déjà effectués | Agent (+1 à chaque envoi) |

---

## Intervention humaine

| Colonne | Action | Effet |
|---------|--------|-------|
| L — Approuver envoi ? | Mettre `OUI` | Déclenche l'envoi au prochain cycle |
| O — Gestion redondances | Changer `Envoyer à nouveau ?` → `Oui` | Déclenche un renvoi |

---

## Agent 2 — `expediteur` (Python pur, sans LLM)

### Fréquence
Toutes les **7 minutes** (`EXPEDITEUR_INTERVAL` dans `.env`).

### Architecture — Python pur
L'expéditeur est orchestré **directement en Python**, sans LLM.
Ce choix garantit l'absence totale d'hallucination sur l'objet ou le corps du message.
L'objet `ExpéditeurRunner` expose une méthode `kickoff()` compatible avec `main.py`.

### Conditions de déclenchement

| Type | Condition | Description |
|------|-----------|-------------|
| `premier_envoi` | L=`OUI` + M=`En attente` | Première fois que ce contact reçoit le Memento |
| `renvoi` | L=`OUI` + M=`Envoyé` + O=`Oui` | Renvoi approuvé manuellement par l'opérateur |

### Lecture du ContenuMessage (Google Doc)

Le fichier **ContenuMessage** est un Google Doc natif exporté en HTML via Drive API.
Notre parser extrait :
- L'objet : texte après le label `Objet :`
- Le corps HTML : paragraphes après `Corps du message :`, liens `<a href="...">` préservés
  (recherche récursive via `find_all("a")` pour trouver les liens dans les `<span>` imbriqués)

Format attendu :
```
Objet :  Memento

Corps du message :
Bonjour,
Veuillez trouver ci-joint Memento en cliquant sur ce lien : [Télécharger le Memento PDF]
Cordialement,
```

### Envoi

Email HTML envoyé via Microsoft Graph API depuis `utilisateur@exemple.fr`.
- Aucune pièce jointe — le Memento est accessible via le lien Google Drive
- `saveToSentItems: true` (copie dans les éléments envoyés)

### Séquence après envoi

| Étape | Action | Outil |
|-------|--------|-------|
| 1 | Envoyer l'email | `SendMailTool` |
| 2a | `premier_envoi` : M → `Envoyé` | `SheetUpdateStatusTool` |
| 2b | `renvoi` : O → vide (anti-boucle) | `SheetClearRedondanceTool` |
| 3 | Q + 1 (compteur d'envois) | `SheetIncrementEnvoisTool` |

---

## Cycle de vie complet d'une demande

```
[Formulaire soumis]
        │
        ▼
  Statut : (non créé)
        │  analyseur_mail détecte
        ▼
  Statut : En attente         ← CAS 1 : nouvelle insertion
        │
        │  intervention humaine : L = OUI
        ▼
  expediteur envoie
        │
        ▼
  Statut : Envoyé + Q = 1     ← premier envoi effectué
        │
        │  même contact refait une demande
        ▼
  O = 'Envoyer à nouveau ?'   ← CAS 3 : redondance signalée
        │
        │  opérateur met O = 'Oui'
        ▼
  expediteur renvoi
        │
        ▼
  Statut : Envoyé + Q = 2 + O = vide   ← renvoi effectué
```

---

## Script batch_migration.py (one-shot)

Script standalone pour importer en masse les emails depuis le dossier Outlook
**"demandes téléchargements mémento 2025"** vers le Google Sheet.

Optimisations :
- **1 seule lecture** du Sheet au démarrage (évite le rate-limit 429)
- Vérification des doublons **en mémoire** (set Python, O(1), 0 appel API)
- `time.sleep(1.1)` entre écritures (respecte le quota 60 writes/min)
- Anti-doublon in-session : mise à jour du set en mémoire après chaque insertion

---

## APIs et services utilisés

| Service | Usage | Authentification |
|---------|-------|-----------------|
| Microsoft Graph API | Lecture Outlook + envoi email + notifications | OAuth 2.0 client credentials (MSAL) |
| Google Sheets API v4 | Lecture/écriture du registre | Compte de service Google |
| Google Drive API v3 | Export HTML du Google Doc ContenuMessage | Compte de service Google |
| Ollama (local VPS) | LLM qwen2.5:14b pour l'agent analyseur | HTTP local `localhost:11434` |

---

## Paramètres configurables (`.env`)

| Variable | Valeur par défaut | Description |
|----------|-------------------|-------------|
| `ANALYSEUR_MAIL_INTERVAL` | `300` (5 min) | Fréquence de polling Outlook |
| `EXPEDITEUR_INTERVAL` | `420` (7 min) | Fréquence de polling Google Sheet |
| `FILTER_SENDER` | `formulaire@exemple.fr` | Expéditeur filtré |
| `GOOGLE_SHEET_TAB` | `Liste_envois_MEMENTO` | Nom de l'onglet |
| `LLM_BASE_URL` | `http://localhost:11434` | URL du serveur Ollama |
| `LLM_MODEL` | `ollama/qwen2.5:14b` | Modèle LLM utilisé |

---

## Sécurité

- `.env` (credentials) → jamais versionné (`.gitignore`)
- `src/config/credentials/` (compte de service Google) → jamais versionné
- `state/last_check_outlook.json` (état runtime) → jamais versionné
- Tokens Microsoft Graph API → générés à la volée, jamais stockés
- LLM → 100% local sur le VPS, aucune donnée envoyée vers l'extérieur

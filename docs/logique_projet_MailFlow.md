# Logique détaillée — Projet MailFlow

## Contexte

L'organisation utilise un formulaire WordPress pour recueillir les demandes d'accès au Memento.
Chaque soumission de formulaire génère un email automatique envoyé depuis `formulaire@exemple.fr`
vers la boite professionnelle de l'utilisateur.

Le système MailFlow automatise la chaîne de traitement : détection de la demande →
enregistrement → approbation manuelle → envoi du lien Memento → confirmation.

La solution est hébergée sur un **VPS privé sous Linux (Oracle)**, ce qui garantit que
les données des demandeurs (nom, email) ne transitent par aucun service cloud tiers
et qu'aucune information n'est envoyée à une API d'inférence externe.

---

## Architecture générale

```
[Formulaire WordPress]
        │
        │ email automatique
        ▼
[Boite Outlook utilisateur]  ◄── Agent analyseur_mail (polling 5 min)
        │
        │ extraction Email / Nom / Prénom
        ▼
[Google Sheet]  ◄──────── Agent expediteur (polling 7 min)
        │
        │ approbation manuelle (colonne "Approuver envoi ?")
        ▼
[Email HTML envoyé] ── lien cliquable ──► [Memento PDF sur Google Drive]
```

---

## Agent 1 — `analyseur_mail`

### Fréquence
Toutes les **5 minutes** (configurable via `ANALYSEUR_MAIL_INTERVAL` dans `.env`).

### Connexion Outlook
Utilise **Microsoft Graph API** avec le flux *client credentials* (OAuth 2.0) :
- `MS_TENANT_ID` + `MS_CLIENT_ID` + `MS_CLIENT_SECRET` → jeton d'accès
- Lecture de la boite `utilisateur@exemple.fr` via l'endpoint `/users/{email}/messages`

### Fetch incrémental
À chaque cycle, l'agent lit le fichier `state/last_check_outlook.json` pour récupérer
le timestamp de la dernière exécution. Il interroge uniquement les emails reçus **après**
ce timestamp, ce qui évite tout doublon et tout retraitement.
Le timestamp est mis à jour à la fin de chaque cycle.

### Filtre des emails

```
expéditeur = "formulaire@exemple.fr"
AND
(
  objet CONTIENT "demande memento"
  OR objet CONTIENT "demande d'accès au memento"
  OR objet CONTIENT "demande accès memento"
  OR objet CONTIENT "accès memento"
)
```

- Le **AND** sur l'expéditeur garantit qu'on ne traite que les emails WordPress officiels.
- Le **OR** sur l'objet couvre les variantes de formulation naturelle du formulaire.

### Extraction Prénom / NOM

L'agent extrait les informations depuis **deux sources** puis conserve la version la plus complète :

| Source | Méthode |
|--------|---------|
| Corps du formulaire | Regex sur les labels `Prénom :` / `Nom :` / `First Name :` / `Last Name :` |
| Champ `From` de l'email | Décomposition du display name (ex. `"Jean Dupont" <...>`) |

**Règle de sélection** : pour chaque champ (prénom, nom), on compare la longueur des deux
valeurs extraites et on conserve la plus longue. Une initiale (`J.`) sera donc écrasée
par un prénom complet (`Jean`) si le formulaire le fournit.

### Écriture dans Google Sheets

Pour chaque email validé, une nouvelle ligne est insérée avec :

| Colonne | Valeur |
|---------|--------|
| A — Email | Adresse email de l'expéditeur |
| B — Nom | Nom extrait (version la plus complète) |
| C — Prenom | Prénom extrait (version la plus complète) |
| D — Approuver envoi ? | **Vide** — à remplir manuellement |
| E — Statut | `En attente` (valeur par défaut automatique) |
| F — Date enregistrement | Timestamp au format `jj/mm/aaaa hh:mm` |

---

## Intervention humaine

Après enregistrement dans Google Sheets, un opérateur humain consulte le fichier
et renseigne la colonne **D — Approuver envoi ?** :

- `OUI` → l'agent `expediteur` traitera cette ligne au prochain cycle
- `NON` ou vide → la ligne est ignorée par l'agent

Cette étape est volontairement manuelle pour garder un contrôle humain avant tout envoi.

---

## Agent 2 — `expediteur`

### Fréquence
Toutes les **7 minutes** (configurable via `EXPEDITEUR_INTERVAL` dans `.env`).

### Lecture du Google Sheet

L'agent scanne toutes les lignes et retient celles qui vérifient **simultanément** :

```
Colonne D (Approuver envoi ?) = "OUI"   [insensible à la casse]
AND
Colonne E (Statut) = "En attente"
```

Le double filtre empêche de renvoyer un email à quelqu'un dont le statut est déjà `Envoyé`.

### Lecture du contenu du message (Google Doc)

Le fichier **ContenuMessage** est un Google Doc natif stocké dans Google Drive.
Il contient l'objet et le corps de l'email à envoyer, avec un lien hypertexte cliquable.

Format attendu dans le document :

```
Objet :  Memento

Corps du message :
Bonjour,
Veuillez trouver ci-joint Memento en cliquant sur ce lien : [Télécharger le Memento PDF]
Cordialement,
```

L'agent exporte le document en **HTML** (via `files().export_media(mimeType="text/html")`)
pour préserver les hyperliens. Il parse ensuite le HTML pour extraire :
- L'objet : texte après le label `Objet :`
- Le corps HTML : paragraphes après `Corps du message :`, avec la balise `<a href="...">` intacte

### Envoi de l'email

L'email est envoyé **depuis la boite de l'utilisateur** (`utilisateur@exemple.fr`) via
Microsoft Graph API (endpoint `sendMail`).

- **Format** : HTML (pour que le lien soit cliquable dans tous les clients email)
- **Pièce jointe** : aucune — le Memento est accessible via le lien Google Drive dans le corps
- **Copie dans les envoyés** : oui (`saveToSentItems: true`)

Le lien de téléchargement direct :
```
https://drive.google.com/uc?export=download&id=VOTRE_FILE_ID
```

### Mise à jour du Statut

Immédiatement après chaque envoi réussi, l'agent met à jour la cellule
de la colonne **E — Statut** de la ligne traitée :

```
En attente  →  Envoyé
```

Cette mise à jour atomique (une ligne à la fois) garantit qu'en cas d'interruption,
les lignes déjà traitées ne seront pas renvoyées au prochain cycle.

---

## Cycle de vie d'une demande

```
[Formulaire soumis]
      │
      ▼
  Statut : (vide)           ← avant la détection par analyseur_mail
      │
      ▼
  Statut : En attente       ← ligne créée par analyseur_mail
      │
      │  (intervention humaine : Approuver envoi ? = OUI)
      ▼
  Statut : En attente  +  Approuver = OUI   ← en attente d'envoi
      │
      ▼
  Statut : Envoyé           ← mis à jour par expediteur après envoi réussi
```

---

## APIs et services utilisés

| Service | Usage | Authentification |
|---------|-------|-----------------|
| Microsoft Graph API | Lecture Outlook + envoi email | OAuth 2.0 client credentials (MSAL) |
| Google Sheets API v4 | Lecture/écriture du registre | Compte de service Google |
| Google Drive API v3 | Export HTML du Google Doc | Compte de service Google |

---

## Paramètres configurables

Tous les paramètres sont centralisés dans `.env` :

| Variable | Valeur par défaut | Description |
|----------|-------------------|-------------|
| `ANALYSEUR_MAIL_INTERVAL` | `300` (5 min) | Fréquence de polling Outlook (secondes) |
| `EXPEDITEUR_INTERVAL` | `420` (7 min) | Fréquence de polling Google Sheet (secondes) |
| `FILTER_SENDER` | `formulaire@exemple.fr` | Expéditeur filtré |
| `GOOGLE_SHEET_TAB` | `Liste_envois_MEMENTO` | Nom de l'onglet dans le Google Sheet |

---

## Sécurité

- Le fichier `.env` (credentials) n'est **jamais versionné** (`.gitignore`)
- Le dossier `config/credentials/` (compte de service Google) n'est **jamais versionné**
- Le fichier `state/last_check_outlook.json` (état runtime) n'est **jamais versionné**
- Les tokens Microsoft Graph API sont générés à la volée à chaque cycle et ne sont pas stockés

# Déploiement MailFlow sur VPS Linux (Oracle)

Ce guide décrit l'installation du projet sur le VPS et sa configuration
en tant que service systemd pour un démarrage automatique au boot.

> **Prérequis :** Ollama + llama3.1 déjà installés et configurés sur le VPS.

---

## 1. Cloner le projet

```bash
cd /home/votre_user          # ou le répertoire souhaité
git clone https://github.com/GuyMartial24/Projet_MailFlow-Multi-agents-IA.git MailFlow
cd MailFlow
```

---

## 2. Créer l'environnement virtuel et installer les dépendances

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Configurer le fichier `.env`

```bash
cp .env.example .env
nano .env     # ou vim .env
```

Renseigner toutes les variables :
- `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_USER_EMAIL`
- `GOOGLE_SHEET_ID`, `GOOGLE_DOC_CONTENU_MESSAGE_ID`
- `LLM_BASE_URL=http://localhost:11434` *(déjà correct)*
- `LLM_MODEL=ollama/llama3.1` *(déjà correct)*

---

## 4. Déposer le fichier Google Service Account

```bash
mkdir -p src/config/credentials
# Copier le fichier JSON du compte de service Google dans :
cp /tmp/google_service_account.json src/config/credentials/google_service_account.json
chmod 600 src/config/credentials/google_service_account.json
```

---

## 5. Tester le projet manuellement (optionnel)

```bash
source .venv/bin/activate
python main.py
# Vérifier que les deux agents démarrent sans erreur
# Ctrl+C pour arrêter
```

---

## 6. Installer le service systemd

### 6.1 Adapter le fichier service

Ouvrir `deploy/mailflow.service` et remplacer les deux placeholders :

| Placeholder | Valeur réelle exemple |
|-------------|----------------------|
| `votre_user` | `ubuntu` ou `oracle` |
| `/chemin/vers/MailFlow` | `/home/ubuntu/MailFlow` |

```bash
nano deploy/mailflow.service
```

### 6.2 Copier le service dans systemd

```bash
sudo cp deploy/mailflow.service /etc/systemd/system/mailflow.service
```

### 6.3 Recharger systemd et activer le service

```bash
sudo systemctl daemon-reload
sudo systemctl enable mailflow     # démarrage automatique au boot
sudo systemctl start mailflow      # démarrage immédiat
```

---

## 7. Vérifier le bon fonctionnement

```bash
# Statut du service
sudo systemctl status mailflow

# Logs en temps réel
sudo journalctl -u mailflow -f

# Logs des dernières 100 lignes
sudo journalctl -u mailflow -n 100
```

---

## 8. Commandes utiles

```bash
# Arrêter le service
sudo systemctl stop mailflow

# Redémarrer le service (après une mise à jour du code)
sudo systemctl restart mailflow

# Désactiver le démarrage automatique
sudo systemctl disable mailflow
```

---

## 9. Mettre à jour le projet

```bash
cd /chemin/vers/MailFlow
git pull origin master
source .venv/bin/activate
pip install -r requirements.txt    # si de nouvelles dépendances ont été ajoutées
sudo systemctl restart mailflow
```

---

## Comportement en cas de redémarrage du VPS

| Événement | Comportement |
|-----------|-------------|
| Redémarrage du VPS | `mailflow.service` redémarre automatiquement après le réseau |
| Crash du processus Python | Redémarrage automatique après 10 secondes (`RestartSec=10s`) |
| Ollama | Déjà configuré indépendamment — aucune dépendance déclarée |

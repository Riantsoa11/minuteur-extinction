# ⚡ Minuteur Extinction

> Une application Windows pour programmer l'arrêt, le redémarrage, la mise en veille, l'hibernation ou le verrouillage de son PC — avec statistiques d'usage, scénarios enchaînés et contrôle à distance.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Fonctionnalités

### 5 modes de déclenchement
- **Minuteur** — durée libre + préréglages personnalisables
- **Heure fixe** — par exemple 02:00 (demain si l'heure est passée)
- **Processus** — l'action se déclenche à la fermeture d'un programme (jeu, build, rendu, installeur)
- **Réseau** — l'action se déclenche quand le débit reste bas pendant N minutes (fin d'une mise à jour Steam, d'un gros `git clone`)
- **Scénario** — chaîne d'actions séquentielle (ex: `30 min → Verrouiller`, `1 h → Veille`, `2 h → Éteindre`)

### 5 actions système
Éteindre · Redémarrer · Veille · Hibernation · Verrouiller

### 📊 Statistiques d'usage
- Temps d'allumage aujourd'hui / cette semaine / ce mois
- Première ouverture et dernière extinction du jour
- Graphique sur 30 jours + moyenne quotidienne
- Top 5 des applications les plus utilisées
- Niveau de batterie et autonomie restante

### 🎨 UX
- 🌙 Thème clair / sombre, auto selon Windows
- 🇫🇷 🇬🇧 Français et anglais
- 📌 Épinglage de la fenêtre
- 📦 Mode compact (fenêtre minimale avec juste l'anneau)
- 🔔 Icône dans la zone de notification Windows avec le compte à rebours dans l'infobulle
- 🪟 Notifications Windows natives à 1 minute de la fin
- ⌨️ Raccourcis : `Entrée` démarre, `Échap` annule

### 🔗 Intégrations
- **Webhook Discord / Slack** : un message est posté après chaque action (`"PC → Éteindre à 23:47"`)
- **API REST locale** : contrôle le PC depuis ton téléphone ou un script
- **Récurrence quotidienne** : chaque jour à HH:MM, action lancée si le PC est inactif depuis N minutes
- **Profils sauvegardés** : enregistre tes configurations favorites (Nuit, Build, Download, Film…)

---

## 📦 Installation

### Option 1 — Exécutable prêt à l'emploi (recommandé)

Télécharge `Minuteur Extinction.exe` depuis la section [Releases](../../releases) et double-clique.

> ⚠️ Windows SmartScreen peut bloquer l'exécutable car il n'est pas signé. Clique sur **Informations complémentaires** → **Exécuter quand même**. Si le **Contrôle intelligent des applications** le bloque sans alternative, préfère l'option 2.

### Option 2 — Depuis les sources

```bash
# Installe Python 3.10+ depuis le Microsoft Store, puis :
pip install -r requirements.txt
python minuteur_extinction.py
```

### Option 3 — Compiler ton propre exécutable

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --icon power.ico --add-data "power.ico;." minuteur_extinction.py
```

---

## 🚀 Utilisation en ligne de commande

Pratique en fin de script de build ou dans une tâche planifiée :

```bash
"Minuteur Extinction.exe" --in 1h30m --action shutdown
"Minuteur Extinction.exe" --at 02:00 --action hibernate
"Minuteur Extinction.exe" --process cargo.exe --action sleep
"Minuteur Extinction.exe" --net --force
```

| Flag | Description |
|------|-------------|
| `--in <durée>` | Durée (`1h30m`, `45m`, `90s`, ou minutes entières) |
| `--at HH:MM` | Heure fixe |
| `--process <nom>` | Nom du processus à surveiller (ex: `cargo.exe`) |
| `--net` | Attendre la fin du téléchargement |
| `--action` | `shutdown` · `restart` · `sleep` · `hibernate` · `lock` |
| `--force` | Forcer la fermeture des applications |

---

## 📱 Contrôle à distance depuis le téléphone

Active l'API REST dans **Paramètres** → une URL comme celle-ci s'affiche :

```
http://192.168.1.42:8787/action?a=shutdown&in=1800&token=xxxxx
```

Ajoute-la à tes favoris mobiles pour éteindre ton PC d'un tap. Pour y accéder hors du Wi-Fi, utilise [Tailscale](https://tailscale.com) ou de la redirection de port.

### Routes

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET`   | `/` | État actuel (JSON) |
| `GET`   | `/action?a=<action>&in=<sec>&token=<...>` | Déclenche une action |

Actions : `shutdown` · `restart` · `sleep` · `hibernate` · `lock` · `cancel`

---

## 💾 Données

Toutes les données sont stockées localement dans :

```
%APPDATA%\MinuteurExtinction\
  ├── config.json      — préférences et paramètres
  ├── usage.json       — statistiques d'usage (90 derniers jours)
  └── profiles.json    — profils enregistrés
```

---

## 🛠️ Stack technique

- **Python 3.10+** avec **Tkinter** (interface native)
- **psutil** pour la surveillance système
- **pystray** + **Pillow** pour l'icône de notification
- **plyer** pour les notifications Windows
- **http.server** (stdlib) pour l'API REST

---

## 📄 Licence

[MIT](LICENSE) © 2026 Tsiory Riantsoa Andrianasoloharison

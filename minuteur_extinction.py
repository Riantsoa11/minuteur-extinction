"""
Minuteur d'extinction v4 — shell app Windows moderne.

Modes de déclenchement :
  Minuteur · Heure fixe · Processus · Réseau · Scénario (enchaîné)

Actions : Éteindre · Redémarrer · Veille · Hibernation · Verrouiller

v4 — Refonte UI style Windows 11 / Fluent :
  • Fenêtre unique redimensionnable (plus de popups) avec sidebar + 5 vues
  • Layout responsive (sidebar s'adapte, vue Timer 1/2/3 colonnes selon largeur)
  • Palette WinUI 3 (Mica dark / light), accents Fluent
  • Garde toute la logique v3 : stats, scenario, API REST, webhook, tray, i18n
"""
import argparse
import ctypes
import datetime as dt
import http.server
import json
import math
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    import customtkinter as ctk
except ImportError:
    print("customtkinter manquant : pip install customtkinter", file=sys.stderr)
    raise
try:
    import psutil
except ImportError:
    psutil = None
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    pystray = Image = ImageDraw = None
try:
    from plyer import notification as plyer_notif
except ImportError:
    plyer_notif = None

SYSTEM = platform.system()
FONT = "Segoe UI" if SYSTEM == "Windows" else "Helvetica"
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MinuteurExtinction")
CFG_PATH = os.path.join(APP_DIR, "config.json")
USAGE_PATH = os.path.join(APP_DIR, "usage.json")
PROFILES_PATH = os.path.join(APP_DIR, "profiles.json")
GRACE = 60

# ========= THÈMES (palette WinUI 3 / Fluent) =========
THEMES = {
    "dark":  {"bg": "#202020",
              "sidebar": "#2b2b2b",
              "card": "#2b2b2b",
              "card_2": "#323232",
              "track": "#3d3d3d",
              "border": "#3d3d3d",
              "hover": "#353535",
              "nav_active": "#2b88d8",
              "text": "#ffffff",
              "text_sec": "#dfdfdf",
              "muted": "#a0a0a0",
              "warn": "#ffb547",
              "accent": "#60cdff"},
    "light": {"bg": "#f3f3f3",
              "sidebar": "#fbfbfb",
              "card": "#fbfbfb",
              "card_2": "#ededed",
              "track": "#e5e5e5",
              "border": "#e5e5e5",
              "hover": "#ededed",
              "nav_active": "#0067c0",
              "text": "#1b1b1b",
              "text_sec": "#333333",
              "muted": "#5c5c5c",
              "warn": "#d58000",
              "accent": "#0067c0"},
}
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32, "xxxl": 48}
FS = {"xs": 10, "sm": 11, "base": 12, "md": 14, "lg": 18, "xl": 24, "display": 40}
RADIUS = {"sm": 4, "md": 6, "lg": 8, "xl": 12, "pill": 999}
SIDEBAR_W = 220
SIDEBAR_W_SMALL = 56
BP_NARROW = 820    # Sidebar passe en icônes seules
BP_MEDIUM = 1050   # Vue Timer passe en 2 colonnes
ACTIONS = {
    "Éteindre": "#ff5c7a", "Redémarrer": "#4da3ff", "Veille": "#b48cff",
    "Hibernation": "#39d0b3", "Verrouiller": "#8fd16a",
}
ACTION_ICONS = {
    "Éteindre": "⏻", "Redémarrer": "↻", "Veille": "☾",
    "Hibernation": "❄", "Verrouiller": "🔒",
}
MODE_ICONS = {
    "Minuteur": "⏱", "Heure fixe": "🕐", "Processus": "⚙",
    "Réseau": "🌐", "Scénario": "🎬",
}
CLI_ACTIONS = {"shutdown": "Éteindre", "restart": "Redémarrer", "sleep": "Veille",
               "hibernate": "Hibernation", "lock": "Verrouiller"}
IGNORED_PROCS = {"svchost.exe", "system", "registry", "idle", "system idle process",
                 "conhost.exe", "csrss.exe", "smss.exe", "wininit.exe", "services.exe",
                 "lsass.exe", "winlogon.exe", "dwm.exe", "fontdrvhost.exe", "runtimebroker.exe",
                 "sihost.exe", "taskhostw.exe", "ctfmon.exe", "searchhost.exe",
                 "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe"}

# ========= INTERNATIONALISATION =========
I18N = {
    "fr": {
        "title": "Minuteur d'extinction",
        "modes": ["Minuteur", "Heure fixe", "Processus", "Réseau", "Scénario"],
        "actions": list(ACTIONS.keys()),
        "start": "Démarrer", "cancel": "Annuler", "firing": "C'est parti…",
        "force": "Forcer la fermeture des applis", "pin": "Épingler",
        "stats": "Statistiques", "settings": "Paramètres", "compact": "Compact",
        "profiles": "Profils", "add_profile": "+ Nouveau profil",
        "today": "Aujourd'hui", "week": "Cette semaine", "month": "Ce mois",
        "first_boot": "Première ouverture", "last_off": "Dernière extinction",
        "avg_daily": "Moyenne / jour (30 j)", "top_apps": "Top 5 applications",
        "battery": "Batterie", "charging": "en charge",
        "scenario_add": "+ Ajouter une étape", "step_delay": "Dans", "then": "puis",
        "net_hint": "Idéal pour une mise à jour Steam ou un gros git clone.",
        "proc_hint": "Se déclenche à la fermeture du processus : jeu, build, rendu…",
        "clock_hint": "Si l'heure est déjà passée, ce sera demain.",
        "warn_minute": "⚠ Plus qu'une minute !", "about_to": "{a} dans…",
        "waiting_proc": "Fermeture de", "download_done": "Téléchargement fini",
        "confirm_title": "Confirmer l'action",
        "confirm_msg": "Tu vas lancer : {a}\n{when}\n\nContinuer ?",
        "confirm_yes": "Oui, lancer", "confirm_no": "Annuler",
        "grace_banner": "⚠ {a} dans {t} — clique pour annuler",
        "nav_timer": "Minuteur", "nav_stats": "Statistiques",
        "nav_profiles": "Profils", "nav_settings": "Paramètres", "nav_help": "Aide",
        "action_section": "Quelle action ?",
        "trigger_section": "Comment déclencher ?",
        "options": "Options",
        "recap_empty": "Choisis une durée pour voir le récapitulatif.",
    },
    "en": {
        "title": "Shutdown Timer",
        "modes": ["Timer", "Fixed time", "Process", "Network", "Scenario"],
        "actions": ["Shut down", "Restart", "Sleep", "Hibernate", "Lock"],
        "start": "Start", "cancel": "Cancel", "firing": "Here we go…",
        "force": "Force applications to close", "pin": "Pin on top",
        "stats": "Statistics", "settings": "Settings", "compact": "Compact",
        "profiles": "Profiles", "add_profile": "+ New profile",
        "today": "Today", "week": "This week", "month": "This month",
        "first_boot": "First boot", "last_off": "Last shutdown",
        "avg_daily": "Daily average (30d)", "top_apps": "Top 5 applications",
        "battery": "Battery", "charging": "charging",
        "scenario_add": "+ Add a step", "step_delay": "In", "then": "then",
        "net_hint": "Perfect for a Steam update or a large git clone.",
        "proc_hint": "Triggered when the process closes: game, build, render…",
        "clock_hint": "If the time has passed, it will be tomorrow.",
        "warn_minute": "⚠ One minute left!", "about_to": "{a} in…",
        "waiting_proc": "Waiting for", "download_done": "Download finished",
        "confirm_title": "Confirm action",
        "confirm_msg": "You're about to run: {a}\n{when}\n\nContinue?",
        "confirm_yes": "Yes, start", "confirm_no": "Cancel",
        "grace_banner": "⚠ {a} in {t} — click to cancel",
        "nav_timer": "Timer", "nav_stats": "Statistics",
        "nav_profiles": "Profiles", "nav_settings": "Settings", "nav_help": "Help",
        "action_section": "Which action?",
        "trigger_section": "How to trigger?",
        "options": "Options",
        "recap_empty": "Pick a duration to preview.",
    },
}

DEFAULT_CFG = {
    "lang": "fr", "theme": "auto", "notify": True, "pin": False, "compact": False,
    "force": False, "presets": [900, 1800, 3600, 7200],
    "last_action": "Éteindre", "last_mode": "Minuteur",
    "last_process": "", "net_threshold": 200, "net_minutes": 3,
    "webhook": "", "api_enabled": False, "api_port": 8787, "api_token": "",
    "recurrent_enabled": False, "recurrent_time": "02:00",
    "recurrent_action": "Éteindre", "recurrent_idle_min": 15,
    "confirm_destructive": True,
    "confirm_threshold_sec": 120,
}
DESTRUCTIVE = {"Éteindre", "Redémarrer", "Hibernation"}


# ========= UTILS CONFIG =========
def ensure_dir():
    os.makedirs(APP_DIR, exist_ok=True)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(default, dict):
            merged = dict(default); merged.update(data); return merged
        return data
    except Exception:
        return json.loads(json.dumps(default))


def save_json(path, data):
    try:
        ensure_dir()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def to_int(v, d=0):
    try: return max(0, int(str(v).strip()))
    except (ValueError, TypeError): return d


def fmt_hms(sec):
    h, r = divmod(int(sec), 3600); m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_short(sec, lang="fr"):
    h, r = divmod(int(sec), 3600); m, s = divmod(r, 60)
    hu, mu = ("h", "min") if lang == "fr" else ("h", "m")
    if h: return f"{h} {hu} {m:02d}" if m else f"{h} {hu}"
    if m: return f"{m} {mu}" if not s else f"{m}:{s:02d}"
    return f"{s} s"


def fmt_duration_long(sec, lang="fr"):
    h, r = divmod(int(sec), 3600); m, _ = divmod(r, 60)
    if lang == "fr":
        if h and m: return f"{h} h {m:02d}"
        if h: return f"{h} h"
        return f"{m} min"
    if h and m: return f"{h}h {m:02d}m"
    if h: return f"{h}h"
    return f"{m}m"


def fmt_speed(bps):
    kb = bps / 1024
    return f"{kb/1024:.1f} Mo/s" if kb >= 1024 else f"{kb:.0f} Ko/s"


def parse_duration(text):
    text = text.strip().lower()
    if text.isdigit(): return int(text) * 60
    total = 0
    for n, unit in re.findall(r"(\d+)\s*([hms])", text):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


# ========= DÉTECTION THÈME WINDOWS =========
def detect_system_dark():
    if SYSTEM != "Windows":
        return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return v == 0
    except Exception:
        return True


# ========= INACTIVITÉ UTILISATEUR =========
def idle_seconds():
    if SYSTEM != "Windows":
        return 0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = LASTINPUTINFO(); lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        tick = ctypes.windll.kernel32.GetTickCount()
        return (tick - lii.dwTime) // 1000
    except Exception:
        return 0


def foreground_proc():
    if SYSTEM != "Windows" or not psutil:
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_uint()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            return psutil.Process(pid.value).name()
    except Exception:
        return None


# ========= PROCESSUS =========
def list_processes():
    names = set()
    if psutil:
        for p in psutil.process_iter(["name"]):
            if p.info["name"]:
                names.add(p.info["name"])
    elif SYSTEM == "Windows":
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout
        names = {line.split('","')[0].strip('"') for line in out.splitlines() if line}
    return sorted((n for n in names if n.lower() not in IGNORED_PROCS), key=str.lower)


def is_running(name):
    name = name.lower()
    return any(n.lower() == name for n in list_processes())


# ========= BATTERIE =========
def battery_info():
    out = {"present": False}
    if psutil:
        try:
            b = psutil.sensors_battery()
            if b:
                out.update(present=True, percent=round(b.percent),
                           plugged=b.power_plugged,
                           autonomy=b.secsleft if b.secsleft > 0 else None)
        except Exception:
            pass
    return out


# ========= ACTIONS SYSTÈME =========
def run_action(action, force=False):
    f = ["/f"] if force else []
    cmds = {
        "Windows": {
            "Éteindre": ["shutdown", "/s", "/t", "0", *f],
            "Redémarrer": ["shutdown", "/r", "/t", "0", *f],
            "Veille": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "Hibernation": ["shutdown", "/h"],
            "Verrouiller": ["rundll32.exe", "user32.dll,LockWorkStation"],
        },
        "Linux": {"Éteindre": ["systemctl", "poweroff"], "Redémarrer": ["systemctl", "reboot"],
                  "Veille": ["systemctl", "suspend"], "Hibernation": ["systemctl", "hibernate"],
                  "Verrouiller": ["loginctl", "lock-session"]},
    }
    cmd = cmds.get(SYSTEM, {}).get(action)
    if cmd:
        flags = 0x08000000 if SYSTEM == "Windows" else 0
        subprocess.Popen(cmd, creationflags=flags)


def beep():
    try:
        if SYSTEM == "Windows":
            import winsound; winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def notify(title, body):
    if not plyer_notif:
        return
    try:
        plyer_notif.notify(title=title, message=body, app_name="Minuteur Extinction", timeout=10)
    except Exception:
        pass


# ========= TRACKING D'USAGE =========
class UsageTracker(threading.Thread):
    """Enregistre toutes les 30 s : uptime du jour + app au premier plan."""
    SAMPLE = 30

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.data = load_json(USAGE_PATH, {"days": {}})

    def today(self):
        return dt.date.today().isoformat()

    def record_boot(self):
        d = self.data["days"].setdefault(self.today(), {"uptime": 0, "first": None, "last": None, "apps": {}})
        if not d["first"]:
            d["first"] = dt.datetime.now().strftime("%H:%M")

    def record_sample(self):
        d = self.data["days"].setdefault(self.today(), {"uptime": 0, "first": None, "last": None, "apps": {}})
        if not d["first"]:
            d["first"] = dt.datetime.now().strftime("%H:%M")
        d["uptime"] += self.SAMPLE
        d["last"] = dt.datetime.now().strftime("%H:%M")
        if idle_seconds() < 60:
            app = foreground_proc()
            if app and app.lower() not in IGNORED_PROCS:
                d["apps"][app] = d["apps"].get(app, 0) + self.SAMPLE
        cutoff = (dt.date.today() - dt.timedelta(days=90)).isoformat()
        for k in list(self.data["days"]):
            if k < cutoff:
                del self.data["days"][k]
        save_json(USAGE_PATH, self.data)

    def run(self):
        self.record_boot(); save_json(USAGE_PATH, self.data)
        while not self.stop_flag.wait(self.SAMPLE):
            try: self.record_sample()
            except Exception: pass

    def stop(self):
        self.stop_flag.set()

    def uptime_today(self):
        return self.data["days"].get(self.today(), {}).get("uptime", 0)

    def uptime_range(self, days):
        total = 0; today = dt.date.today()
        for i in range(days):
            d = (today - dt.timedelta(days=i)).isoformat()
            total += self.data["days"].get(d, {}).get("uptime", 0)
        return total

    def daily_series(self, days=30):
        today = dt.date.today(); out = []
        for i in range(days - 1, -1, -1):
            d = (today - dt.timedelta(days=i)).isoformat()
            out.append((d, self.data["days"].get(d, {}).get("uptime", 0)))
        return out

    def first_last_today(self):
        d = self.data["days"].get(self.today(), {})
        return d.get("first"), d.get("last")

    def top_apps(self, n=5, days=7):
        agg = {}; today = dt.date.today()
        for i in range(days):
            day = (today - dt.timedelta(days=i)).isoformat()
            for a, s in self.data["days"].get(day, {}).get("apps", {}).items():
                agg[a] = agg.get(a, 0) + s
        return sorted(agg.items(), key=lambda x: -x[1])[:n]


# ========= WEBHOOK =========
def send_webhook(url, text):
    if not url:
        return
    try:
        payload = {"content": text} if "discord" in url else {"text": text}
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# ========= API REST =========
class ApiServer(threading.Thread):
    def __init__(self, app, port, token):
        super().__init__(daemon=True)
        self.app, self.port, self.token = app, port, token
        self.server = None

    def run(self):
        app, token = self.app, self.token

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(s, *a): pass

            def _json(s, obj, code=200):
                b = json.dumps(obj).encode()
                s.send_response(code); s.send_header("Content-Type", "application/json")
                s.send_header("Access-Control-Allow-Origin", "*")
                s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)

            def do_GET(s):
                p = urllib.parse.urlparse(s.path); q = urllib.parse.parse_qs(p.query)
                if p.path == "/":
                    s._json({"state": app.state_, "action": app.action.get(),
                             "mode": app.mode.get(),
                             "remaining": max(0, int(app.deadline - time.time())) if app.state_ == "countdown" else 0})
                elif p.path == "/action":
                    if q.get("token", [""])[0] != token:
                        return s._json({"error": "bad token"}, 403)
                    a = q.get("a", [""])[0]
                    if a == "cancel":
                        app.after(0, app._cancel); return s._json({"ok": True})
                    if a in CLI_ACTIONS:
                        secs = to_int(q.get("in", ["0"])[0]) or 1
                        app.after(0, lambda: app._api_trigger(CLI_ACTIONS[a], secs))
                        return s._json({"ok": True, "in": secs})
                    s._json({"error": "unknown action"}, 400)
                else:
                    s._json({"error": "not found"}, 404)

        try:
            self.server = http.server.HTTPServer(("0.0.0.0", self.port), H)
            self.server.serve_forever()
        except Exception:
            pass

    def stop(self):
        if self.server:
            try: self.server.shutdown()
            except Exception: pass


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"


# ========= DIALOG DE CONFIRMATION =========
class ConfirmDialog(ctk.CTkToplevel):
    """Modale de confirmation pour actions destructives."""

    def __init__(self, parent, action, when_text, on_confirm):
        super().__init__(parent)
        self.app = parent; c = parent.theme; t = parent.t
        self.title(t["confirm_title"]); self.configure(fg_color=c["bg"])
        self.resizable(False, False); self.transient(parent); self.grab_set()
        self._fired = False
        self.on_confirm = on_confirm
        accent = ACTIONS[action]

        wrap = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0)
        wrap.pack(padx=SP["xl"], pady=SP["lg"])

        head = ctk.CTkFrame(wrap, fg_color="transparent"); head.pack(fill="x")
        tk.Label(head, text="⚠", bg=c["bg"], fg=accent,
                 font=(FONT, FS["display"], "bold")).pack(side="left", padx=(0, SP["md"]))
        headr = ctk.CTkFrame(head, fg_color="transparent"); headr.pack(side="left", fill="x", expand=True)
        tk.Label(headr, text=t["confirm_title"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["lg"], "bold"), anchor="w").pack(fill="x")
        tk.Label(headr, text=parent._act_key2label.get(action, action), bg=c["bg"], fg=accent,
                 font=(FONT, FS["md"], "bold"), anchor="w").pack(fill="x")

        tk.Label(wrap, text=when_text, bg=c["bg"], fg=c["muted"],
                 font=(FONT, FS["sm"]), justify="left",
                 wraplength=380).pack(fill="x", pady=(SP["md"], SP["lg"]))

        btns = ctk.CTkFrame(wrap, fg_color="transparent"); btns.pack(fill="x")
        cancel = ctk.CTkButton(btns, text=t["confirm_no"], command=self._cancel,
                                fg_color=c["card"], hover_color=c["hover"],
                                text_color=c["text"], font=ctk.CTkFont(FONT, FS["md"], "bold"),
                                height=42, corner_radius=RADIUS["md"],
                                border_width=1, border_color=c["border"])
        cancel.pack(side="left", expand=True, fill="x", padx=(0, SP["xs"]))
        ctk.CTkButton(btns, text=t["confirm_yes"], command=self._confirm,
                      fg_color=accent, hover_color=accent, text_color="#ffffff",
                      font=ctk.CTkFont(FONT, FS["md"], "bold"),
                      height=42, corner_radius=RADIUS["md"]).pack(
            side="left", expand=True, fill="x", padx=(SP["xs"], 0))

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Return>", lambda e: self._confirm())
        cancel.focus_set()

        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

    def _confirm(self):
        if self._fired: return
        self._fired = True
        self.grab_release(); self.destroy()
        try: self.on_confirm()
        except Exception: pass

    def _cancel(self):
        if self._fired: return
        self._fired = True
        self.grab_release(); self.destroy()


# ========= APPLICATION =========
class App(ctk.CTk):
    """Shell app Windows : sidebar + content frame, 5 vues internes.
    Fenêtre unique redimensionnable, pas de popups (sauf ConfirmDialog modal)."""

    RING = 220

    def __init__(self, args):
        is_dark = (load_json(CFG_PATH, DEFAULT_CFG).get("theme") == "auto" and detect_system_dark()) \
                  or load_json(CFG_PATH, DEFAULT_CFG).get("theme") == "dark"
        ctk.set_appearance_mode("dark" if is_dark else "light")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.cfg = load_json(CFG_PATH, DEFAULT_CFG)
        if not self.cfg.get("api_token"):
            self.cfg["api_token"] = secrets.token_urlsafe(12); save_json(CFG_PATH, self.cfg)
        self.profiles = load_json(PROFILES_PATH, [])
        self.lang = self.cfg["lang"]; self.t = I18N[self.lang]
        self.theme = THEMES["dark" if is_dark else "light"]

        self._act_label2key = dict(zip(self.t["actions"], list(ACTIONS.keys())))
        self._act_key2label = {v: k for k, v in self._act_label2key.items()}
        self._mode_label2key = dict(zip(self.t["modes"],
                                         ["Minuteur", "Heure fixe", "Processus", "Réseau", "Scénario"]))
        self._mode_key2label = {v: k for k, v in self._mode_label2key.items()}

        self.title(self.t["title"])
        self.configure(fg_color=self.theme["bg"])
        self.minsize(640, 580)
        self.geometry("1000x680")
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            self.iconbitmap(os.path.join(base, "power.ico"))
        except Exception:
            pass

        now = dt.datetime.now() + dt.timedelta(hours=1)
        self.mode = tk.StringVar(value=self.cfg["last_mode"])
        self.action = tk.StringVar(value=self.cfg["last_action"])
        self.h = tk.StringVar(value="0"); self.m = tk.StringVar(value="30"); self.s = tk.StringVar(value="0")
        self.ah = tk.StringVar(value=f"{now.hour:02d}"); self.am = tk.StringVar(value="00")
        self.proc = tk.StringVar(value=self.cfg["last_process"])
        self.net_thr = tk.StringVar(value=str(self.cfg["net_threshold"]))
        self.net_min = tk.StringVar(value=str(self.cfg["net_minutes"]))
        self.force = tk.BooleanVar(value=self.cfg["force"])
        self.pin = tk.BooleanVar(value=self.cfg["pin"])
        self.scenario = self.cfg.get("scenario", [{"delay": 1800, "action": "Verrouiller"}])

        self.state_ = "idle"
        self.jobs = {}
        self.deadline = self.total = 0
        self.warned = False
        self.reason = ""
        self.idle_s = 0
        self.speed = 0.0
        self._last_bytes = None
        self.spin_angle = 90
        self.inputs = []
        self.scenario_queue = []
        self.compact = False
        self.current_view = "timer"
        self._grace_visible = False
        self._sidebar_compact = False
        self._last_width = 0
        self._timer_cols = 0  # 1, 2 ou 3 colonnes

        self.tracker = UsageTracker(); self.tracker.start()
        self.api_server = None
        if self.cfg["api_enabled"]:
            self._start_api()

        self._style()
        self._build_shell()
        self._show_view("timer")

        for v in (self.h, self.m, self.s, self.ah, self.am, self.proc, self.net_thr, self.net_min):
            v.trace_add("write", lambda *_: self._refresh_idle())
        self.attributes("-topmost", self.pin.get())
        self.bind("<Return>", lambda e: self._start() if self.state_ == "idle" else None)
        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Control-comma>", lambda e: self._show_view("settings"))
        self.bind("<Control-k>", lambda e: self.toggle_compact())
        self.bind("<Control-K>", lambda e: self.toggle_compact())
        self.bind("<F1>", lambda e: self._show_view("help"))
        self.bind("<Configure>", self._on_resize)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._net_loop()
        self._clock_loop()
        self._recurrent_loop()
        self._tray_setup()
        self._apply_cli(args)

    # ---- Styles ttk legacy ----
    def _style(self):
        c = self.theme
        st = ttk.Style(self)
        try: st.theme_use("clam")
        except tk.TclError: pass
        st.configure("Dark.TCombobox", fieldbackground=c["card_2"], background=c["card_2"],
                     foreground=c["text"], arrowcolor=c["text"], bordercolor=c["border"],
                     lightcolor=c["card_2"], darkcolor=c["card_2"],
                     selectbackground=c["card_2"], selectforeground=c["text"], padding=6)
        st.map("Dark.TCombobox",
               fieldbackground=[("readonly", c["card_2"]), ("disabled", c["card_2"])],
               foreground=[("disabled", c["muted"])])
        self.option_add("*TCombobox*Listbox.background", c["card_2"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["track"])

    # ========= SHELL (SIDEBAR + CONTENT) =========
    def _build_shell(self):
        c = self.theme
        # Nettoyage éventuel
        for w in self.winfo_children():
            try: w.destroy()
            except Exception: pass

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")

    def _build_sidebar(self):
        c = self.theme
        self.sidebar = ctk.CTkFrame(self, width=SIDEBAR_W, corner_radius=0,
                                     fg_color=c["sidebar"])
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)

        # Logo + titre
        head = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        head.pack(fill="x", padx=SP["md"], pady=(SP["lg"], SP["xl"]))
        tk.Label(head, text="⚡", bg=c["sidebar"], fg=c["accent"],
                 font=(FONT, FS["xl"], "bold")).pack(side="left")
        self.sidebar_title = tk.Label(head, text="  " + self.t["title"],
                                       bg=c["sidebar"], fg=c["text"],
                                       font=(FONT, FS["md"], "bold"))
        self.sidebar_title.pack(side="left")

        # Boutons de navigation
        self.nav_buttons = {}
        navs = [
            ("timer", "⏱", self.t["nav_timer"]),
            ("stats", "📊", self.t["nav_stats"]),
            ("profiles", "💾", self.t["nav_profiles"]),
            ("settings", "⚙", self.t["nav_settings"]),
            ("help", "❓", self.t["nav_help"]),
        ]
        for name, icon, label in navs:
            self.nav_buttons[name] = self._nav_button(self.sidebar, icon, label, name)

        # Spacer + boutons bas (pin, compact)
        tk.Label(self.sidebar, bg=c["sidebar"]).pack(expand=True, fill="both")

        bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom.pack(fill="x", padx=SP["sm"], pady=SP["sm"])
        self.pin_btn = self._icon_toggle(bottom, "📌", "Épingler" if self.lang == "fr" else "Pin",
                                          self._toggle_pin, active=self.pin.get())
        self.pin_btn.pack(fill="x", pady=2)
        self._icon_toggle(bottom, "🗗", self.t["compact"], self.toggle_compact).pack(
            fill="x", pady=2)

    def _nav_button(self, parent, icon, label, view_name):
        c = self.theme
        active = (self.current_view == view_name)
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", padx=SP["sm"], pady=1)
        # Indicateur gauche (barre bleue si actif)
        indic = tk.Frame(container, bg=c["nav_active"] if active else c["sidebar"], width=3)
        indic.pack(side="left", fill="y", padx=(2, 0))
        btn = ctk.CTkButton(container, text=f"  {icon}   {label}", anchor="w",
                             command=lambda: self._show_view(view_name),
                             fg_color=c["hover"] if active else "transparent",
                             hover_color=c["hover"],
                             text_color=c["text"],
                             font=ctk.CTkFont(FONT, FS["base"], "bold" if active else "normal"),
                             height=38, corner_radius=RADIUS["md"])
        btn.pack(side="left", fill="x", expand=True, padx=(SP["xs"], SP["xs"]))
        container._indic = indic
        container._btn = btn
        container._icon = icon
        container._label = label
        return container

    def _icon_toggle(self, parent, icon, label, cmd, active=False):
        c = self.theme
        b = ctk.CTkButton(parent, text=f"  {icon}   {label}", anchor="w", command=cmd,
                           fg_color=c["hover"] if active else "transparent",
                           hover_color=c["hover"], text_color=c["text"],
                           font=ctk.CTkFont(FONT, FS["sm"]),
                           height=32, corner_radius=RADIUS["sm"])
        return b

    def _highlight_nav(self):
        c = self.theme
        for name, container in self.nav_buttons.items():
            is_active = (name == self.current_view)
            container._indic.configure(bg=c["nav_active"] if is_active else c["sidebar"])
            container._btn.configure(
                fg_color=c["hover"] if is_active else "transparent",
                font=ctk.CTkFont(FONT, FS["base"], "bold" if is_active else "normal"))

    # ========= RESPONSIVE =========
    def _on_resize(self, event):
        if event.widget is not self: return
        w = event.width
        if w == self._last_width: return
        self._last_width = w
        # Sidebar : narrow passe en icônes
        want_compact = w < BP_NARROW
        if want_compact != self._sidebar_compact:
            self._sidebar_compact = want_compact
            self._apply_sidebar_mode()
        # Vue timer : relayout si colonnes changent
        if self.current_view == "timer":
            want_cols = 3 if w >= BP_MEDIUM else (2 if w >= 820 else 1)
            if want_cols != self._timer_cols:
                self._show_view("timer")  # Rebuild la vue

    def _apply_sidebar_mode(self):
        """Bascule la sidebar entre mode large (texte visible) et compact (icônes seules)."""
        c = self.theme
        if self._sidebar_compact:
            self.sidebar.configure(width=SIDEBAR_W_SMALL)
            self.sidebar_title.pack_forget()
            for name, container in self.nav_buttons.items():
                container._btn.configure(text=f"  {container._icon}")
        else:
            self.sidebar.configure(width=SIDEBAR_W)
            self.sidebar_title.pack(side="left")
            for name, container in self.nav_buttons.items():
                container._btn.configure(text=f"  {container._icon}   {container._label}")

    # ========= NAVIGATION ENTRE VUES =========
    def _show_view(self, name):
        self.current_view = name
        # Détruit tous les enfants du content
        for w in self.content.winfo_children():
            try: w.destroy()
            except Exception: pass
        self.inputs = []
        self._highlight_nav()
        if name == "timer": self._view_timer()
        elif name == "stats": self._view_stats()
        elif name == "profiles": self._view_profiles()
        elif name == "settings": self._view_settings()
        elif name == "help": self._view_help()

    # ========= VUE TIMER =========
    def _view_timer(self):
        c = self.theme
        w = self.winfo_width() or 1000
        cols = 3 if w >= BP_MEDIUM else (2 if w >= 820 else 1)
        self._timer_cols = cols

        # Wrapper principal avec padding
        wrap = ctk.CTkFrame(self.content, fg_color=c["bg"])
        wrap.pack(fill="both", expand=True, padx=SP["xl"], pady=SP["xl"])

        # Titre de page
        tk.Label(wrap, text=self.t["nav_timer"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["xl"], "bold")).pack(anchor="w", pady=(0, SP["lg"]))

        # Zone principale en grille (cols variables)
        grid = ctk.CTkFrame(wrap, fg_color="transparent")
        grid.pack(fill="both", expand=True)

        if cols == 3:
            grid.grid_columnconfigure(0, weight=0, minsize=300)
            grid.grid_columnconfigure(1, weight=1)
            grid.grid_columnconfigure(2, weight=0, minsize=300)
            grid.grid_rowconfigure(0, weight=1)
            self._timer_col_trigger(grid, 0, 0)
            self._timer_col_center(grid, 0, 1)
            self._timer_col_action(grid, 0, 2)
        elif cols == 2:
            grid.grid_columnconfigure(0, weight=1)
            grid.grid_columnconfigure(1, weight=0, minsize=300)
            grid.grid_rowconfigure(0, weight=1)
            self._timer_col_center(grid, 0, 0)
            right = ctk.CTkFrame(grid, fg_color="transparent")
            right.grid(row=0, column=1, sticky="nsew", padx=(SP["md"], 0))
            self._timer_col_trigger(right, 0, 0, side_pack=True)
            self._timer_col_action(right, 1, 0, side_pack=True)
        else:  # 1 colonne
            grid.grid_columnconfigure(0, weight=1)
            self._timer_col_trigger(grid, 0, 0, side_pack=True)
            self._timer_col_center(grid, 1, 0, side_pack=True)
            self._timer_col_action(grid, 2, 0, side_pack=True)

        self._refresh_idle()

    def _timer_col_trigger(self, parent, row, col, side_pack=False):
        c = self.theme
        card = self._card(parent)
        if side_pack:
            card.grid(row=row, column=col, sticky="new", pady=(0, SP["md"]))
            parent.grid_rowconfigure(row, weight=0)
        else:
            card.grid(row=row, column=col, sticky="nsew", padx=(0, SP["md"]))

        self._card_title(card, self.t["trigger_section"])
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=SP["lg"], pady=(0, SP["lg"]))

        # Choix du mode (5 pills verticaux)
        for key, label in zip(["Minuteur", "Heure fixe", "Processus", "Réseau", "Scénario"],
                                self.t["modes"]):
            active = (self.mode.get() == key)
            icon = MODE_ICONS.get(key, "")
            b = ctk.CTkButton(
                inner, text=f"  {icon}   {label}", anchor="w",
                command=lambda k=key: (self._set_mode(k), self._show_view("timer")),
                fg_color=c["track"] if active else c["card_2"],
                hover_color=c["hover"], text_color=c["text"],
                font=ctk.CTkFont(FONT, FS["sm"], "bold" if active else "normal"),
                height=34, corner_radius=RADIUS["sm"])
            b.pack(fill="x", pady=2)

        # Panneau de paramètres du mode courant
        tk.Label(inner, bg=c["card"], height=1).pack()
        self._timer_mode_panel(inner)

    def _timer_mode_panel(self, parent):
        c = self.theme
        mode = self.mode.get()
        pad = ctk.CTkFrame(parent, fg_color="transparent")
        pad.pack(fill="x", pady=(SP["md"], 0))

        if mode == "Minuteur":
            # Presets
            presets_row = ctk.CTkFrame(pad, fg_color="transparent")
            presets_row.pack(fill="x", pady=(0, SP["sm"]))
            for sec in self.cfg.get("presets", [900, 1800, 3600, 7200]):
                b = ctk.CTkButton(presets_row, text=fmt_short(sec, self.lang),
                                   command=lambda s=sec: self._use_preset(s),
                                   fg_color=c["card_2"], hover_color=c["hover"],
                                   text_color=c["text"],
                                   font=ctk.CTkFont(FONT, FS["xs"]),
                                   height=26, width=56, corner_radius=RADIUS["sm"])
                b.pack(side="left", padx=2)
            # Spinboxes h/m/s
            row = ctk.CTkFrame(pad, fg_color="transparent"); row.pack(fill="x")
            for var, to_v, unit in ((self.h, 23, "h"), (self.m, 59, "min"), (self.s, 59, "s")):
                col = ctk.CTkFrame(row, fg_color="transparent")
                col.pack(side="left", padx=SP["xs"])
                self._spin(col, var, to_v).pack()
                tk.Label(col, text=unit, bg=c["card"], fg=c["muted"],
                         font=(FONT, FS["xs"])).pack(pady=(2, 0))

        elif mode == "Heure fixe":
            row = ctk.CTkFrame(pad, fg_color="transparent"); row.pack()
            self._spin(row, self.ah, 23).pack(side="left")
            tk.Label(row, text=":", bg=c["card"], fg=c["text"],
                     font=(FONT, FS["lg"], "bold")).pack(side="left", padx=SP["xs"])
            self._spin(row, self.am, 59).pack(side="left")
            tk.Label(pad, text=self.t["clock_hint"], bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["xs"]), wraplength=240,
                     justify="left").pack(pady=(SP["sm"], 0))

        elif mode == "Processus":
            self.combo = ttk.Combobox(pad, textvariable=self.proc, style="Dark.TCombobox",
                                       font=(FONT, FS["base"]),
                                       postcommand=self._refresh_procs)
            self.combo.pack(fill="x", pady=(0, SP["sm"]))
            self.inputs.append(self.combo)
            tk.Label(pad, text=self.t["proc_hint"], bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["xs"]), wraplength=240,
                     justify="left").pack()

        elif mode == "Réseau":
            row = ctk.CTkFrame(pad, fg_color="transparent"); row.pack(fill="x")
            tk.Label(row, text="< " if self.lang == "fr" else "< ", bg=c["card"],
                     fg=c["muted"], font=(FONT, FS["sm"])).pack(side="left")
            self._spin(row, self.net_thr, 99999, width=5).pack(side="left")
            tk.Label(row, text=" Ko/s pdt ", bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["sm"])).pack(side="left")
            self._spin(row, self.net_min, 120).pack(side="left")
            tk.Label(row, text=" min", bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["sm"])).pack(side="left")
            self.speed_lbl = tk.Label(pad, text="— Ko/s", bg=c["card"], fg=c["muted"],
                                       font=(FONT, FS["xs"]))
            self.speed_lbl.pack(pady=(SP["sm"], 0))
            tk.Label(pad, text=self.t["net_hint"], bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["xs"]), wraplength=240,
                     justify="left").pack()

        else:  # Scénario
            for i, step in enumerate(self.scenario):
                r = ctk.CTkFrame(pad, fg_color=c["card_2"], corner_radius=RADIUS["sm"])
                r.pack(fill="x", pady=2)
                tk.Label(r, text=f"{i+1}.", bg=c["card_2"], fg=c["muted"],
                         font=(FONT, FS["sm"], "bold")).pack(side="left", padx=SP["sm"])
                tk.Label(r, text=f"{fmt_short(step['delay'], self.lang)} → {step['action']}",
                         bg=c["card_2"], fg=ACTIONS[step['action']],
                         font=(FONT, FS["sm"])).pack(side="left", pady=SP["xs"])
                ctk.CTkButton(r, text="✕", command=lambda i=i: self._scn_del(i),
                               width=28, height=24, fg_color="transparent",
                               hover_color=c["hover"], text_color=c["muted"]).pack(side="right", padx=2)
            ctk.CTkButton(pad, text=self.t["scenario_add"], command=self._scn_add,
                           fg_color=c["card_2"], hover_color=c["hover"],
                           text_color=c["text"], height=30,
                           font=ctk.CTkFont(FONT, FS["xs"])).pack(fill="x", pady=(SP["xs"], 0))

    def _timer_col_center(self, parent, row, col, side_pack=False):
        c = self.theme
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        if side_pack:
            wrap.grid(row=row, column=col, sticky="nsew", pady=(0, SP["md"]))
        else:
            wrap.grid(row=row, column=col, sticky="nsew")

        s = self.RING
        self.canvas = tk.Canvas(wrap, width=s, height=s, bg=c["bg"], highlightthickness=0)
        self.canvas.pack(pady=(SP["md"], SP["sm"]))
        m = 12; box = (m, m, s - m, s - m)
        self.canvas.create_oval(*box, outline=c["track"], width=10)
        self.arc = self.canvas.create_arc(*box, start=90, extent=0, style="arc",
                                           width=10, outline=self._accent())
        self.t_main = self.canvas.create_text(s/2, s/2 - 8, fill=c["text"],
                                               font=(FONT, FS["display"] - 4, "bold"))
        self.t_sub = self.canvas.create_text(s/2, s/2 + 22, fill=c["muted"],
                                              font=(FONT, FS["sm"]))
        self.t_eta = self.canvas.create_text(s/2, s/2 + 42, fill=c["muted"],
                                              font=(FONT, FS["xs"]))

        # Récap dynamique
        self.recap_lbl = tk.Label(wrap, text="", bg=c["bg"], fg=c["muted"],
                                   font=(FONT, FS["sm"], "italic"))
        self.recap_lbl.pack(fill="x", pady=(SP["md"], SP["sm"]))

        # Bannière de grâce (cachée par défaut)
        self.grace_banner = ctk.CTkButton(
            wrap, text="", command=self._cancel,
            fg_color=c["warn"], hover_color=c["warn"], text_color="#000000",
            font=ctk.CTkFont(FONT, FS["md"], "bold"),
            height=38, corner_radius=RADIUS["md"])
        self._grace_visible = False

        # Boutons +5/+15/+1h (visibles pendant countdown)
        self.extend_row = ctk.CTkFrame(wrap, fg_color="transparent")
        self.extend_row.pack(fill="x")

        # Bouton primaire
        self.main_btn = ctk.CTkButton(
            wrap, text=self.t["start"], command=self._toggle,
            fg_color=self._accent(), hover_color=self._accent(),
            text_color="#ffffff", font=ctk.CTkFont(FONT, FS["md"], "bold"),
            height=48, corner_radius=RADIUS["md"])
        self.main_btn.pack(fill="x", pady=(SP["sm"], 0))

        if self.state_ == "countdown":
            self._lock(True)
            if self.warned:
                self._show_grace_banner()

    def _timer_col_action(self, parent, row, col, side_pack=False):
        c = self.theme
        card = self._card(parent)
        if side_pack:
            card.grid(row=row, column=col, sticky="new")
            parent.grid_rowconfigure(row, weight=0)
        else:
            card.grid(row=row, column=col, sticky="nsew", padx=(SP["md"], 0))

        self._card_title(card, self.t["action_section"])
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=SP["lg"], pady=(0, SP["lg"]))

        # 5 boutons d'action (grille 1 colonne de boutons pleine largeur)
        for key, label in zip(ACTIONS.keys(), self.t["actions"]):
            active = (self.action.get() == key)
            icon = ACTION_ICONS.get(key, "")
            accent = ACTIONS[key]
            b = ctk.CTkButton(
                inner, text=f"  {icon}   {label}", anchor="w",
                command=lambda k=key: (self._set_action(k), self._show_view("timer")),
                fg_color=accent if active else c["card_2"],
                hover_color=accent if active else c["hover"],
                text_color="#ffffff" if active else c["text"],
                font=ctk.CTkFont(FONT, FS["base"], "bold" if active else "normal"),
                height=38, corner_radius=RADIUS["sm"])
            b.pack(fill="x", pady=2)

        # Options
        tk.Label(inner, text=self.t["options"], bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["xs"], "bold")).pack(anchor="w", pady=(SP["md"], SP["xs"]))
        self.force_chk = ctk.CTkCheckBox(
            inner, text=self.t["force"], variable=self.force, command=self._save,
            font=ctk.CTkFont(FONT, FS["sm"]), text_color=c["text_sec"],
            fg_color=self._accent(), hover_color=self._accent(),
            border_color=c["border"], checkmark_color="#ffffff",
            checkbox_width=18, checkbox_height=18, corner_radius=RADIUS["sm"])
        self.force_chk.pack(anchor="w")

    # ---- Helpers UI ----
    def _card(self, parent):
        c = self.theme
        return ctk.CTkFrame(parent, fg_color=c["card"], corner_radius=RADIUS["lg"],
                             border_width=1, border_color=c["border"])

    def _card_title(self, card, text):
        c = self.theme
        tk.Label(card, text=text, bg=c["card"], fg=c["text"],
                 font=(FONT, FS["md"], "bold"),
                 anchor="w").pack(fill="x", padx=SP["lg"], pady=(SP["lg"], SP["md"]))

    def _spin(self, parent, var, to, width=3):
        c = self.theme
        sp = tk.Spinbox(parent, from_=0, to=to, textvariable=var, width=width,
                        font=(FONT, FS["lg"], "bold"), justify="center",
                        bg=c["card_2"], fg=c["text"], buttonbackground=c["card_2"],
                        relief="flat", insertbackground=c["text"], wrap=True,
                        highlightthickness=1, highlightbackground=c["border"],
                        highlightcolor=c["accent"],
                        disabledbackground=c["card_2"], disabledforeground=c["muted"])
        self.inputs.append(sp)
        var.trace_add("write",
                      lambda *_, v=var, m=to, w=sp: self._validate_input(v, m, w))
        return sp

    def _validate_input(self, var, max_v, widget):
        c = self.theme
        try:
            v = int(str(var.get()).strip() or "0")
            ok = 0 <= v <= max_v
        except (ValueError, TypeError): ok = False
        try: widget.configure(highlightbackground=c["border"] if ok else "#ff5c7a")
        except Exception: pass

    # ========= VUE STATS =========
    def _view_stats(self):
        c = self.theme
        scroll = ctk.CTkScrollableFrame(self.content, fg_color=c["bg"])
        scroll.pack(fill="both", expand=True, padx=SP["xl"], pady=SP["xl"])
        tk.Label(scroll, text=self.t["nav_stats"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["xl"], "bold")).pack(anchor="w", pady=(0, SP["lg"]))

        t = self.tracker
        # Rangée 1
        row = ctk.CTkFrame(scroll, fg_color="transparent"); row.pack(fill="x", pady=(0, SP["sm"]))
        for lbl, val in [(self.t["today"], fmt_duration_long(t.uptime_today(), self.lang)),
                         (self.t["week"], fmt_duration_long(t.uptime_range(7), self.lang)),
                         (self.t["month"], fmt_duration_long(t.uptime_range(30), self.lang))]:
            self._stat_card(row, lbl, val).pack(side="left", expand=True, fill="x", padx=SP["xs"])
        # Rangée 2
        first, last = t.first_last_today()
        avg = t.uptime_range(30) // 30
        row2 = ctk.CTkFrame(scroll, fg_color="transparent"); row2.pack(fill="x", pady=(0, SP["md"]))
        for lbl, val in [(self.t["first_boot"], first or "—"),
                         (self.t["last_off"], last or "—"),
                         (self.t["avg_daily"], fmt_duration_long(avg, self.lang))]:
            self._stat_card(row2, lbl, val).pack(side="left", expand=True, fill="x", padx=SP["xs"])

        # Graphique 30 jours
        tk.Label(scroll, text=("📊 30 derniers jours" if self.lang == "fr" else "📊 30 last days"),
                 bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["md"], "bold")).pack(anchor="w", pady=(SP["md"], SP["xs"]))
        chart_card = self._card(scroll); chart_card.pack(fill="x")
        series = t.daily_series(30)
        gw, gh = 700, 150; ML, MR, MT, MB = 50, 10, 14, 24
        iw, ih = gw - ML - MR, gh - MT - MB
        g = tk.Canvas(chart_card, width=gw, height=gh, bg=c["card"], highlightthickness=0)
        g.pack(padx=SP["md"], pady=SP["md"])
        peak = max((v for _, v in series), default=1) or 1
        for frac in (0.0, 0.5, 1.0):
            y = MT + ih - frac * ih
            g.create_line(ML, y, ML + iw, y, fill=c["track"], width=1,
                          dash=(2, 3) if 0 < frac < 1 else None)
            lbl = fmt_duration_long(int(peak * frac), self.lang) if frac > 0 else "0"
            g.create_text(ML - 6, y, text=lbl, anchor="e", fill=c["muted"],
                          font=(FONT, FS["xs"] - 1))
        bw = iw / len(series); accent = ACTIONS[self.action.get()]
        for i, (_, v) in enumerate(series):
            x = ML + i * bw + bw * 0.15
            x2 = ML + (i + 1) * bw - bw * 0.15
            h = (v / peak) * ih if peak else 0
            if v: g.create_rectangle(x, MT + ih - h, x2, MT + ih, fill=accent, outline="")
        for frac, idx in ((0.0, 0), (0.5, len(series) // 2), (1.0, len(series) - 1)):
            x = ML + frac * iw
            d = dt.date.fromisoformat(series[idx][0])
            offset = (dt.date.today() - d).days
            if offset == 0: lbl = ("auj." if self.lang == "fr" else "today")
            else: lbl = (f"-{offset}j" if self.lang == "fr" else f"-{offset}d")
            g.create_text(x, MT + ih + 12, text=lbl, anchor="n", fill=c["muted"],
                          font=(FONT, FS["xs"] - 1))

        # Top apps
        tk.Label(scroll, text=("🏆 " + self.t["top_apps"]), bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["md"], "bold")).pack(anchor="w", pady=(SP["lg"], SP["xs"]))
        top_card = self._card(scroll); top_card.pack(fill="x")
        top = t.top_apps(5, 7); mx = max((v for _, v in top), default=1) or 1
        if not top:
            tk.Label(top_card, text=("Pas encore de données." if self.lang == "fr"
                                      else "No data yet."),
                     bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["sm"])).pack(pady=SP["md"])
        else:
            for name, sec in top:
                r = ctk.CTkFrame(top_card, fg_color="transparent")
                r.pack(fill="x", padx=SP["md"], pady=SP["xs"])
                tk.Label(r, text=name, bg=c["card"], fg=c["text"],
                         font=(FONT, FS["sm"]), width=28, anchor="w").pack(side="left")
                bar = tk.Frame(r, bg=c["track"], height=14)
                bar.pack(side="left", fill="x", expand=True, padx=SP["sm"])
                fill = tk.Frame(bar, bg=c["accent"], height=14)
                fill.place(x=0, y=0, relwidth=sec / mx, relheight=1)
                tk.Label(r, text=fmt_duration_long(sec, self.lang), bg=c["card"],
                         fg=c["muted"], font=(FONT, FS["sm"]), width=10,
                         anchor="e").pack(side="right")

        # Batterie
        tk.Label(scroll, text=("🔋 " + self.t["battery"]), bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["md"], "bold")).pack(anchor="w", pady=(SP["lg"], SP["xs"]))
        batt_card = self._card(scroll); batt_card.pack(fill="x")
        b = battery_info()
        if b["present"]:
            txt = f"{b['percent']} %  —  "
            txt += self.t["charging"] if b["plugged"] else (
                "sur batterie" if self.lang == "fr" else "on battery")
            if b["autonomy"]:
                txt += f"  ·  ~ {fmt_duration_long(b['autonomy'], self.lang)}"
        else:
            txt = ("PC fixe (pas de batterie détectée)" if self.lang == "fr"
                   else "No battery detected")
        tk.Label(batt_card, text=txt, bg=c["card"], fg=c["text"],
                 font=(FONT, FS["md"])).pack(anchor="w", padx=SP["md"], pady=SP["md"])

    def _stat_card(self, parent, label, value):
        c = self.theme
        card = self._card(parent)
        tk.Label(card, text=label, bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["xs"])).pack(anchor="w", padx=SP["md"], pady=(SP["md"], 2))
        tk.Label(card, text=value, bg=c["card"], fg=c["text"],
                 font=(FONT, FS["lg"], "bold")).pack(anchor="w", padx=SP["md"],
                                                       pady=(0, SP["md"]))
        return card

    # ========= VUE PROFILES =========
    def _view_profiles(self):
        c = self.theme
        wrap = ctk.CTkFrame(self.content, fg_color=c["bg"])
        wrap.pack(fill="both", expand=True, padx=SP["xl"], pady=SP["xl"])
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", pady=(0, SP["lg"]))
        tk.Label(head, text=self.t["nav_profiles"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["xl"], "bold")).pack(side="left")
        ctk.CTkButton(head, text=self.t["add_profile"], command=self._add_profile,
                       fg_color=self._accent(), hover_color=self._accent(),
                       text_color="#ffffff",
                       font=ctk.CTkFont(FONT, FS["sm"], "bold"),
                       height=32, corner_radius=RADIUS["md"]).pack(side="right")

        scroll = ctk.CTkScrollableFrame(wrap, fg_color=c["bg"])
        scroll.pack(fill="both", expand=True)
        if not self.profiles:
            card = self._card(scroll); card.pack(fill="x")
            tk.Label(card,
                     text=("Aucun profil pour le moment. Clique sur « + Nouveau profil »."
                           if self.lang == "fr"
                           else "No profiles yet. Click « + New profile »."),
                     bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["sm"])).pack(pady=SP["xl"])
            return
        for i, pr in enumerate(self.profiles):
            card = self._card(scroll); card.pack(fill="x", pady=SP["xs"])
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=SP["md"], pady=SP["md"])
            info = ctk.CTkFrame(r, fg_color="transparent"); info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=pr["name"], bg=c["card"], fg=c["text"],
                     font=(FONT, FS["md"], "bold"), anchor="w").pack(fill="x")
            tk.Label(info, text=f"{pr['mode']} → {pr['action']}", bg=c["card"],
                     fg=ACTIONS.get(pr['action'], c["muted"]),
                     font=(FONT, FS["xs"]), anchor="w").pack(fill="x")
            ctk.CTkButton(r, text=("Charger" if self.lang == "fr" else "Load"),
                           command=lambda p=pr: self._load_profile(p),
                           fg_color=c["card_2"], hover_color=c["hover"], text_color=c["text"],
                           font=ctk.CTkFont(FONT, FS["xs"]),
                           width=80, height=30, corner_radius=RADIUS["sm"]).pack(side="right", padx=SP["xs"])
            ctk.CTkButton(r, text="✕", command=lambda i=i: self._del_profile(i),
                           fg_color="transparent", hover_color=c["hover"], text_color=c["muted"],
                           width=30, height=30).pack(side="right")

    def _add_profile(self):
        name = simpledialog.askstring("Nouveau profil", "Nom du profil :", parent=self)
        if not name: return
        self.profiles.append({
            "name": name, "mode": self.mode.get(), "action": self.action.get(),
            "h": self.h.get(), "m": self.m.get(), "s": self.s.get(),
            "ah": self.ah.get(), "am": self.am.get(),
            "process": self.proc.get(), "net_thr": self.net_thr.get(),
            "net_min": self.net_min.get(),
            "scenario": [dict(st) for st in self.scenario],
        })
        save_json(PROFILES_PATH, self.profiles)
        self._show_view("profiles")

    def _del_profile(self, i):
        del self.profiles[i]; save_json(PROFILES_PATH, self.profiles)
        self._show_view("profiles")

    def _load_profile(self, pr):
        self._cancel()
        self.mode.set(pr["mode"]); self.action.set(pr["action"])
        self.h.set(pr.get("h", "0")); self.m.set(pr.get("m", "30")); self.s.set(pr.get("s", "0"))
        self.ah.set(pr.get("ah", "02")); self.am.set(pr.get("am", "00"))
        self.proc.set(pr.get("process", ""))
        self.net_thr.set(pr.get("net_thr", "200")); self.net_min.set(pr.get("net_min", "3"))
        self.scenario = pr.get("scenario", self.scenario)
        self._save()
        self._show_view("timer")

    # ========= VUE SETTINGS =========
    def _view_settings(self):
        c = self.theme
        scroll = ctk.CTkScrollableFrame(self.content, fg_color=c["bg"])
        scroll.pack(fill="both", expand=True, padx=SP["xl"], pady=SP["xl"])
        tk.Label(scroll, text=self.t["nav_settings"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["xl"], "bold")).pack(anchor="w", pady=(0, SP["lg"]))

        cfg = self.cfg

        # Apparence
        g = self._card(scroll); g.pack(fill="x", pady=SP["xs"])
        self._settings_section(g, "🎨  " + ("Apparence" if self.lang == "fr" else "Appearance"))

        r = ctk.CTkFrame(g, fg_color="transparent"); r.pack(fill="x", padx=SP["lg"], pady=SP["xs"])
        tk.Label(r, text=("Langue" if self.lang == "fr" else "Language"), bg=c["card"],
                 fg=c["muted"], font=(FONT, FS["sm"]), width=18, anchor="w").pack(side="left")
        lang_seg = ctk.CTkSegmentedButton(r, values=["Français", "English"],
                                           command=lambda v: self._change_lang("fr" if v.startswith("Fr") else "en"),
                                           fg_color=c["card_2"], selected_color=c["track"],
                                           unselected_color=c["card_2"], text_color=c["text"],
                                           corner_radius=RADIUS["sm"], height=30)
        lang_seg.set("Français" if cfg["lang"] == "fr" else "English")
        lang_seg.pack(side="left")

        r = ctk.CTkFrame(g, fg_color="transparent"); r.pack(fill="x", padx=SP["lg"], pady=(SP["xs"], SP["lg"]))
        tk.Label(r, text=("Thème" if self.lang == "fr" else "Theme"), bg=c["card"],
                 fg=c["muted"], font=(FONT, FS["sm"]), width=18, anchor="w").pack(side="left")
        theme_seg = ctk.CTkSegmentedButton(
            r, values=["Auto", "Sombre" if self.lang == "fr" else "Dark",
                        "Clair" if self.lang == "fr" else "Light"],
            command=lambda v: self.apply_theme(
                {"Auto": "auto", "Sombre": "dark", "Dark": "dark",
                 "Clair": "light", "Light": "light"}[v]),
            fg_color=c["card_2"], selected_color=c["track"],
            unselected_color=c["card_2"], text_color=c["text"],
            corner_radius=RADIUS["sm"], height=30)
        theme_seg.set({"auto": "Auto",
                        "dark": "Sombre" if self.lang == "fr" else "Dark",
                        "light": "Clair" if self.lang == "fr" else "Light"}[cfg["theme"]])
        theme_seg.pack(side="left")

        # Sécurité
        g = self._card(scroll); g.pack(fill="x", pady=SP["xs"])
        self._settings_section(g, "🛡  Sécurité")
        cv = tk.BooleanVar(value=cfg.get("confirm_destructive", True))
        ctk.CTkSwitch(g, text=("Confirmation avant Éteindre / Redémarrer / Hibernation"
                               if self.lang == "fr"
                               else "Confirm before Shutdown / Restart / Hibernate"),
                       variable=cv, command=lambda: self._set("confirm_destructive", cv.get()),
                       progress_color=self._accent(), fg_color=c["track"],
                       text_color=c["text"],
                       font=ctk.CTkFont(FONT, FS["sm"])).pack(anchor="w", padx=SP["lg"],
                                                                pady=SP["xs"])
        r = ctk.CTkFrame(g, fg_color="transparent"); r.pack(fill="x", padx=SP["lg"], pady=(SP["xs"], SP["lg"]))
        tk.Label(r, text=("Seuil (sec)" if self.lang == "fr" else "Threshold (sec)"),
                 bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["sm"]), width=18, anchor="w").pack(side="left")
        tv2 = tk.StringVar(value=str(cfg.get("confirm_threshold_sec", 120)))
        ctk.CTkEntry(r, textvariable=tv2, width=80, height=30,
                      fg_color=c["card_2"], text_color=c["text"],
                      border_color=c["border"], justify="center",
                      font=ctk.CTkFont(FONT, FS["sm"])).pack(side="left")
        tv2.trace_add("write",
                      lambda *_: self._set("confirm_threshold_sec", to_int(tv2.get(), 120)))

        # Notifications
        g = self._card(scroll); g.pack(fill="x", pady=SP["xs"])
        self._settings_section(g, "🔔  Notifications")
        nv = tk.BooleanVar(value=cfg["notify"])
        ctk.CTkSwitch(g, text=("Notifications Windows natives (à 1 min de la fin)"
                               if self.lang == "fr"
                               else "Native Windows notifications (1 min before)"),
                       variable=nv, command=lambda: self._set("notify", nv.get()),
                       progress_color=self._accent(), fg_color=c["track"],
                       text_color=c["text"],
                       font=ctk.CTkFont(FONT, FS["sm"])).pack(anchor="w", padx=SP["lg"],
                                                                pady=(SP["xs"], SP["lg"]))

        # Récurrence
        g = self._card(scroll); g.pack(fill="x", pady=SP["xs"])
        self._settings_section(g, "⏰  Récurrence")
        rv = tk.BooleanVar(value=cfg["recurrent_enabled"])
        ctk.CTkSwitch(g, text=("Lancer l'action chaque jour si inactif"
                               if self.lang == "fr"
                               else "Trigger daily if idle"),
                       variable=rv, command=lambda: self._set("recurrent_enabled", rv.get()),
                       progress_color=self._accent(), fg_color=c["track"],
                       text_color=c["text"],
                       font=ctk.CTkFont(FONT, FS["sm"])).pack(anchor="w", padx=SP["lg"],
                                                                pady=SP["xs"])
        r = ctk.CTkFrame(g, fg_color="transparent"); r.pack(fill="x", padx=SP["lg"], pady=SP["xs"])
        tk.Label(r, text=("Heure" if self.lang == "fr" else "Time"), bg=c["card"],
                 fg=c["muted"], font=(FONT, FS["sm"]), width=10, anchor="w").pack(side="left")
        hv = tk.StringVar(value=cfg["recurrent_time"])
        ctk.CTkEntry(r, textvariable=hv, width=70, height=28, fg_color=c["card_2"],
                      text_color=c["text"], border_color=c["border"],
                      justify="center",
                      font=ctk.CTkFont(FONT, FS["sm"])).pack(side="left")
        hv.trace_add("write", lambda *_: self._set("recurrent_time", hv.get()))
        tk.Label(r, text=("  Inactif ≥" if self.lang == "fr" else "  Idle ≥"),
                 bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["sm"])).pack(side="left", padx=(SP["md"], 0))
        iv = tk.StringVar(value=str(cfg["recurrent_idle_min"]))
        ctk.CTkEntry(r, textvariable=iv, width=50, height=28, fg_color=c["card_2"],
                      text_color=c["text"], border_color=c["border"],
                      justify="center",
                      font=ctk.CTkFont(FONT, FS["sm"])).pack(side="left", padx=SP["xs"])
        tk.Label(r, text="min", bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["sm"])).pack(side="left")
        iv.trace_add("write",
                     lambda *_: self._set("recurrent_idle_min", to_int(iv.get(), 15)))
        r2 = ctk.CTkFrame(g, fg_color="transparent"); r2.pack(fill="x", padx=SP["lg"], pady=(SP["xs"], SP["lg"]))
        tk.Label(r2, text="Action", bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["sm"]), width=10, anchor="w").pack(side="left")
        av = tk.StringVar(value=cfg["recurrent_action"])
        actions_labels = [self._act_key2label[k] for k in ACTIONS]
        current = self._act_key2label.get(cfg["recurrent_action"], actions_labels[0])
        menu = ctk.CTkOptionMenu(r2, values=actions_labels,
                                  command=lambda v: self._set("recurrent_action",
                                                               self._act_label2key.get(v, v)),
                                  fg_color=c["card_2"], button_color=c["card_2"],
                                  button_hover_color=c["hover"], text_color=c["text"],
                                  dropdown_fg_color=c["card"], dropdown_hover_color=c["hover"],
                                  dropdown_text_color=c["text"],
                                  corner_radius=RADIUS["sm"], width=140, height=28)
        menu.set(current); menu.pack(side="left")

        # Webhook
        g = self._card(scroll); g.pack(fill="x", pady=SP["xs"])
        self._settings_section(g, "💬  Webhook (Discord / Slack)")
        wv = tk.StringVar(value=cfg["webhook"])
        ctk.CTkEntry(g, textvariable=wv, height=32, fg_color=c["card_2"],
                      text_color=c["text"], border_color=c["border"],
                      font=ctk.CTkFont(FONT, FS["sm"])).pack(fill="x", padx=SP["lg"],
                                                                pady=(0, SP["sm"]))
        wv.trace_add("write", lambda *_: self._set("webhook", wv.get().strip()))
        tk.Label(g, text=("URL postée après chaque action (vide = désactivé)."
                           if self.lang == "fr"
                           else "URL posted after each action (empty = disabled)."),
                 bg=c["card"], fg=c["muted"], font=(FONT, FS["xs"]),
                 wraplength=600, justify="left").pack(anchor="w", padx=SP["lg"],
                                                       pady=(0, SP["lg"]))

        # API REST
        g = self._card(scroll); g.pack(fill="x", pady=SP["xs"])
        self._settings_section(g, "📱  API REST")
        av2 = tk.BooleanVar(value=cfg["api_enabled"])
        ctk.CTkSwitch(g, text=f"Serveur HTTP activé (port {cfg['api_port']})",
                       variable=av2, command=lambda: self._api(av2.get()),
                       progress_color=self._accent(), fg_color=c["track"],
                       text_color=c["text"],
                       font=ctk.CTkFont(FONT, FS["sm"])).pack(anchor="w", padx=SP["lg"], pady=SP["xs"])
        ip = lan_ip()
        url = f"http://{ip}:{cfg['api_port']}/action?a=shutdown&in=1800&token={cfg['api_token']}"
        urlbox = ctk.CTkEntry(g, height=28, fg_color=c["card_2"], text_color=c["text"],
                               border_color=c["border"],
                               font=ctk.CTkFont(FONT, FS["xs"]))
        urlbox.insert(0, url); urlbox.configure(state="readonly")
        urlbox.pack(fill="x", padx=SP["lg"], pady=SP["xs"])
        tk.Label(g, text="Actions : shutdown · restart · sleep · hibernate · lock · cancel",
                 bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["xs"])).pack(anchor="w", padx=SP["lg"], pady=(0, SP["lg"]))

    def _settings_section(self, card, title):
        c = self.theme
        tk.Label(card, text=title, bg=c["card"], fg=c["text"],
                 font=(FONT, FS["md"], "bold"),
                 anchor="w").pack(fill="x", padx=SP["lg"], pady=(SP["lg"], SP["md"]))

    def _set(self, k, v):
        self.cfg[k] = v; save_json(CFG_PATH, self.cfg)

    def _api(self, enabled):
        self._set("api_enabled", enabled)
        if enabled: self._start_api()
        else: self._stop_api()

    def _change_lang(self, v):
        if v == self.lang: return
        self._set("lang", v); self.lang = v; self.t = I18N[v]
        self._act_label2key = dict(zip(self.t["actions"], list(ACTIONS.keys())))
        self._act_key2label = {v: k for k, v in self._act_label2key.items()}
        self._mode_label2key = dict(zip(self.t["modes"],
                                         ["Minuteur", "Heure fixe", "Processus", "Réseau", "Scénario"]))
        self._mode_key2label = {v: k for k, v in self._mode_label2key.items()}
        self.title(self.t["title"])
        # Rebuild sidebar + vue courante
        self._build_shell()
        self._show_view(self.current_view)

    # ========= VUE HELP =========
    def _view_help(self):
        c = self.theme
        wrap = ctk.CTkFrame(self.content, fg_color=c["bg"])
        wrap.pack(fill="both", expand=True, padx=SP["xl"], pady=SP["xl"])
        tk.Label(wrap, text=self.t["nav_help"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["xl"], "bold")).pack(anchor="w", pady=(0, SP["lg"]))

        # Raccourcis
        card = self._card(wrap); card.pack(fill="x", pady=SP["xs"])
        self._settings_section(card, "⌨  " + ("Raccourcis clavier" if self.lang == "fr"
                                                 else "Keyboard shortcuts"))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=SP["lg"], pady=(0, SP["lg"]))
        shortcuts = [
            ("Entrée / Enter", "Démarrer l'action" if self.lang == "fr" else "Start action"),
            ("Échap / Esc", "Annuler" if self.lang == "fr" else "Cancel"),
            ("Tab", "Naviguer entre les champs" if self.lang == "fr" else "Navigate fields"),
            ("Ctrl + ,", "Ouvrir les paramètres" if self.lang == "fr" else "Open settings"),
            ("Ctrl + K", "Mode compact" if self.lang == "fr" else "Toggle compact"),
            ("F1", "Afficher cette aide" if self.lang == "fr" else "Show this help"),
        ]
        for key, desc in shortcuts:
            r = ctk.CTkFrame(inner, fg_color="transparent")
            r.pack(fill="x", pady=SP["xs"])
            kchip = tk.Label(r, text=key, bg=c["card_2"], fg=c["text"],
                              font=(FONT, FS["sm"], "bold"),
                              padx=10, pady=3)
            kchip.pack(side="left")
            tk.Label(r, text=desc, bg=c["card"], fg=c["muted"],
                     font=(FONT, FS["sm"])).pack(side="left", padx=SP["md"])

        # À propos
        card = self._card(wrap); card.pack(fill="x", pady=SP["xs"])
        self._settings_section(card, "ℹ  " + ("À propos" if self.lang == "fr" else "About"))
        info = (f"Version : v4 — refonte UI\n"
                f"Python : {platform.python_version()}\n"
                f"Config : {CFG_PATH}")
        tk.Label(card, text=info, bg=c["card"], fg=c["muted"],
                 font=(FONT, FS["xs"]), justify="left").pack(
            anchor="w", padx=SP["lg"], pady=(0, SP["lg"]))

    # ========= LOGIQUE MÉTIER (identique v3) =========
    def _accent(self):
        return ACTIONS[self.action.get()]

    def _hms(self):
        return to_int(self.h.get()) * 3600 + to_int(self.m.get()) * 60 + to_int(self.s.get())

    def _use_preset(self, sec):
        h, r = divmod(sec, 3600); m, s = divmod(r, 60)
        self.h.set(str(h)); self.m.set(str(m)); self.s.set(str(s))

    def _secs_until_clock(self):
        now = dt.datetime.now()
        target = now.replace(hour=min(to_int(self.ah.get()), 23),
                             minute=min(to_int(self.am.get()), 59), second=0, microsecond=0)
        if target <= now: target += dt.timedelta(days=1)
        return int((target - now).total_seconds()), target

    def _set_mode(self, name, save=True):
        if self.state_ != "idle": return
        self.mode.set(name)
        if save: self._save()

    def _set_action(self, name, save=True):
        if self.state_ != "idle": return
        self.action.set(name)
        if save: self._save()

    def _save(self):
        self.cfg.update(
            last_action=self.action.get(), last_mode=self.mode.get(),
            force=self.force.get(), pin=self.pin.get(),
            last_process=self.proc.get().strip(),
            net_threshold=to_int(self.net_thr.get(), 200),
            net_minutes=to_int(self.net_min.get(), 3), scenario=self.scenario,
            lang=self.lang)
        save_json(CFG_PATH, self.cfg)

    def _toggle_pin(self):
        self.pin.set(not self.pin.get())
        self.attributes("-topmost", self.pin.get())
        self._save()
        # Rebuild sidebar pour l'état actif
        self._build_shell()
        self._show_view(self.current_view)

    def _refresh_procs(self):
        if not hasattr(self, "combo"): return
        try:
            self.combo.configure(state="disabled")
            self._proc_loading = True
            self._refresh_procs_spinner()
        except Exception: pass
        def worker():
            procs = []
            try: procs = list_processes()
            except Exception: pass
            self.after(0, lambda: self._refresh_procs_done(procs))
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_procs_spinner(self):
        if not getattr(self, "_proc_loading", False): return
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._proc_spin_i = (getattr(self, "_proc_spin_i", 0) + 1) % len(frames)
        try: self.combo.set(f"{frames[self._proc_spin_i]} " +
                             ("Chargement…" if self.lang == "fr" else "Loading…"))
        except Exception: pass
        self.after(80, self._refresh_procs_spinner)

    def _refresh_procs_done(self, procs):
        self._proc_loading = False
        try:
            self.combo["values"] = procs
            self.combo.set(self.proc.get() or "")
            if self.state_ == "idle": self.combo.configure(state="normal")
        except Exception: pass

    def _ring(self, main, sub="", eta="", big=True):
        if not hasattr(self, "canvas"): return
        c = self.canvas
        c.itemconfigure(self.t_main, text=main,
                        font=(FONT, (FS["display"] - 4) if big else FS["lg"], "bold"))
        c.itemconfigure(self.t_sub, text=sub)
        c.itemconfigure(self.t_eta, text=eta)

    def _refresh_idle(self):
        if self.state_ != "idle": return
        if not hasattr(self, "canvas"): return
        act, mode = self.action.get(), self.mode.get()
        self.canvas.itemconfigure(self.arc, start=90, outline=self._accent())
        if mode == "Minuteur":
            sec = self._hms()
            end = (dt.datetime.now() + dt.timedelta(seconds=sec)).strftime("%H:%M")
            self._ring(fmt_hms(sec), self.t["about_to"].format(a=act),
                       f"→ {end}" if sec else "")
            self.canvas.itemconfigure(self.arc, extent=-359.9 if sec else 0)
        elif mode == "Heure fixe":
            sec, target = self._secs_until_clock()
            self._ring(target.strftime("%H:%M"),
                       (f"{act} à cette heure" if self.lang == "fr"
                        else f"{act} at this time"),
                       (f"dans {fmt_short(sec, self.lang)}" if self.lang == "fr"
                        else f"in {fmt_short(sec, self.lang)}"))
            self.canvas.itemconfigure(self.arc, extent=-359.9)
        elif mode == "Processus":
            name = self.proc.get().strip() or "..."
            self._ring("…", f"{act} — {self.t['waiting_proc']}", name, big=False)
            self.canvas.itemconfigure(self.arc, extent=-90)
        elif mode == "Réseau":
            self._ring("Réseau", f"{act} quand débit <",
                       f"{to_int(self.net_thr.get())} Ko/s / {to_int(self.net_min.get())} min",
                       big=False)
            self.canvas.itemconfigure(self.arc, extent=-90)
        else:  # Scénario
            total = sum(st["delay"] for st in self.scenario)
            self._ring(f"{len(self.scenario)} étapes" if self.lang == "fr"
                       else f"{len(self.scenario)} steps",
                       "Chaîne d'actions" if self.lang == "fr" else "Action chain",
                       f"total {fmt_short(total, self.lang)}", big=False)
            self.canvas.itemconfigure(self.arc, extent=-359.9)
        if hasattr(self, "recap_lbl"):
            self.recap_lbl.configure(text=self._build_recap())

    def _build_recap(self):
        act, mode, lang = self.action.get(), self.mode.get(), self.lang
        if mode == "Minuteur":
            sec = self._hms()
            if sec <= 0: return self.t["recap_empty"]
            end = (dt.datetime.now() + dt.timedelta(seconds=sec)).strftime("%H:%M")
            return (f"→ {act} dans {fmt_short(sec, lang)} (à {end})" if lang == "fr"
                    else f"→ {act} in {fmt_short(sec, lang)} (at {end})")
        if mode == "Heure fixe":
            sec, target = self._secs_until_clock()
            when = target.strftime("%H:%M")
            day = (" demain" if target.date() > dt.date.today() else "") if lang == "fr" \
                  else (" tomorrow" if target.date() > dt.date.today() else "")
            return (f"→ {act} à {when}{day} (dans {fmt_short(sec, lang)})" if lang == "fr"
                    else f"→ {act} at {when}{day} (in {fmt_short(sec, lang)})")
        if mode == "Processus":
            name = self.proc.get().strip() or "…"
            return (f"→ {act} à la fermeture de « {name} »" if lang == "fr"
                    else f"→ {act} when « {name} » closes")
        if mode == "Réseau":
            return (f"→ {act} quand débit < {to_int(self.net_thr.get())} Ko/s "
                    f"pendant {to_int(self.net_min.get())} min" if lang == "fr"
                    else f"→ {act} when speed < {to_int(self.net_thr.get())} KB/s "
                    f"for {to_int(self.net_min.get())} min")
        total = sum(st["delay"] for st in self.scenario)
        return (f"→ {len(self.scenario)} étapes, total {fmt_short(total, lang)}"
                if lang == "fr"
                else f"→ {len(self.scenario)} steps, total {fmt_short(total, lang)}")

    def _clock_loop(self):
        if self.state_ == "idle" and self.mode.get() in ("Minuteur", "Heure fixe"):
            self._refresh_idle()
        self.after(15000, self._clock_loop)

    def _after(self, key, ms, fn):
        if key in self.jobs: self.after_cancel(self.jobs[key])
        self.jobs[key] = self.after(ms, fn)

    def _stop_jobs(self):
        for j in self.jobs.values():
            try: self.after_cancel(j)
            except Exception: pass
        self.jobs.clear()

    def _toggle(self):
        self._cancel() if self.state_ != "idle" else self._start()

    def _needs_confirmation(self, mode):
        if not self.cfg.get("confirm_destructive", True): return False
        act = self.action.get()
        if act not in DESTRUCTIVE: return False
        if mode == "Scénario":
            return any(st["action"] in DESTRUCTIVE for st in self.scenario)
        thr = int(self.cfg.get("confirm_threshold_sec", 120))
        if mode == "Minuteur":
            return self._hms() < thr or act == "Éteindre"
        if mode == "Heure fixe":
            return self._secs_until_clock()[0] < thr or act == "Éteindre"
        return True

    def _start(self):
        if self.state_ != "idle": return
        mode = self.mode.get()
        if mode == "Minuteur" and self._hms() <= 0:
            return messagebox.showwarning("Durée", "Choisis une durée > 0.")
        if mode == "Processus":
            name = self.proc.get().strip()
            if not name: return messagebox.showwarning("Processus", "Choisis un processus.")
            if not is_running(name): return messagebox.showwarning("Processus", f"« {name} » n'est pas en cours.")
        if mode == "Réseau" and not psutil:
            return messagebox.showerror("Réseau", "psutil manquant.")
        if mode == "Scénario" and not self.scenario:
            return messagebox.showwarning("Scénario", "Aucune étape.")
        if self._needs_confirmation(mode):
            when = self._build_recap()
            msg = self.t["confirm_msg"].format(
                a=self._act_key2label.get(self.action.get(), self.action.get()), when=when)
            ConfirmDialog(self, self.action.get(), msg, on_confirm=self._do_start)
            return
        self._do_start()

    def _do_start(self):
        mode = self.mode.get()
        if mode == "Minuteur":
            self._lock(True); self._begin_countdown(self._hms())
        elif mode == "Heure fixe":
            self._lock(True); self._begin_countdown(self._secs_until_clock()[0])
        elif mode == "Processus":
            self._lock(True); self.state_ = "waiting"; self._watch_process(); self._spinner()
        elif mode == "Réseau":
            self._lock(True); self.state_ = "waiting"; self.idle_s = 0; self._spinner()
        else:
            self._lock(True); self.scenario_queue = list(self.scenario); self._next_scenario()
        self._save()

    def _next_scenario(self):
        if not self.scenario_queue:
            self.state_ = "idle"; self._lock(False); self._refresh_idle(); return
        step = self.scenario_queue.pop(0)
        self.action.set(step["action"])
        accent = self._accent()
        self.canvas.itemconfigure(self.arc, outline=accent)
        self.main_btn.configure(fg_color=self.theme["track"], hover_color=self.theme["hover"])
        self._begin_countdown(step["delay"], reason=f"Étape · {step['action']}")

    def _lock(self, locked):
        for w in self.inputs:
            try: w.configure(state="disabled" if locked else "normal")
            except Exception: pass
        accent = self._accent()
        if locked:
            self.main_btn.configure(text=self.t["cancel"], fg_color=self.theme["track"],
                                     hover_color=self.theme["hover"], text_color=self.theme["text"])
        else:
            self.main_btn.configure(text=self.t["start"], fg_color=accent,
                                     hover_color=accent, text_color="#ffffff")

    def _begin_countdown(self, sec, reason=""):
        self.state_ = "countdown"; self.total = sec
        self.deadline = time.time() + sec; self.reason = reason; self.warned = False
        self._hide_grace_banner()
        self._render_extend(True); self._tick()

    def _render_extend(self, show):
        if not hasattr(self, "extend_row"): return
        for w in self.extend_row.winfo_children(): w.destroy()
        if not show: return
        c = self.theme
        inner = ctk.CTkFrame(self.extend_row, fg_color="transparent"); inner.pack()
        for label, sec in (("+5 min", 300), ("+15 min", 900), ("+1 h", 3600)):
            ctk.CTkButton(inner, text=label, command=lambda s=sec: self._extend(s),
                           fg_color=c["card_2"], hover_color=c["hover"],
                           text_color=c["text"],
                           font=ctk.CTkFont(FONT, FS["xs"]),
                           height=28, width=60, corner_radius=RADIUS["sm"]).pack(
                side="left", padx=SP["xs"])

    def _extend(self, sec):
        if self.state_ != "countdown": return
        self.deadline += sec; self.total += sec; self.warned = False
        self.attributes("-topmost", self.pin.get())
        self.canvas.itemconfigure(self.arc, outline=self._accent())
        if self.deadline - time.time() > 60: self._hide_grace_banner()

    def _tick(self):
        rem = max(0.0, self.deadline - time.time()); shown = math.ceil(rem)
        end = dt.datetime.fromtimestamp(self.deadline).strftime("%H:%M:%S")
        sub = self.reason or self.t["about_to"].format(a=self.action.get())
        self._ring(fmt_hms(shown), sub, f"→ {end}")
        if hasattr(self, "canvas"):
            self.canvas.itemconfigure(self.arc, start=90,
                                       extent=-359.9 * rem / max(self.total, 1))
        if rem <= 60 and not self.warned:
            self.warned = True
            if hasattr(self, "canvas"):
                self.canvas.itemconfigure(self.arc, outline=self.theme["warn"])
            self.deiconify(); self.attributes("-topmost", True); self.lift(); beep()
            if self.cfg["notify"]:
                notify(self.t["title"], self.t["warn_minute"] + f" ({self.action.get()})")
            self._show_grace_banner()
        if self._grace_visible and hasattr(self, "grace_banner"):
            self.grace_banner.configure(
                text=self.t["grace_banner"].format(
                    a=self._act_key2label.get(self.action.get(), self.action.get()),
                    t=fmt_hms(shown)[3:]))
        if rem <= 0: return self._fire()
        self._after("tick", 200, self._tick)

    def _show_grace_banner(self):
        if self._grace_visible or not hasattr(self, "grace_banner"): return
        self._grace_visible = True
        self.grace_banner.pack(fill="x", pady=(SP["xs"], SP["xs"]), before=self.main_btn)

    def _hide_grace_banner(self):
        if not self._grace_visible or not hasattr(self, "grace_banner"): return
        self._grace_visible = False
        try: self.grace_banner.pack_forget()
        except Exception: pass

    def _spinner(self):
        if self.state_ != "waiting" or not hasattr(self, "canvas"): return
        self.spin_angle = (self.spin_angle - 6) % 360
        self.canvas.itemconfigure(self.arc, start=self.spin_angle, extent=-90,
                                   outline=self._accent())
        self._after("anim", 30, self._spinner)

    def _watch_process(self):
        if self.state_ != "waiting": return
        name = self.proc.get().strip()
        self._ring("…", f"{self.t['waiting_proc']}", name, big=False)
        if not is_running(name):
            return self._begin_countdown(GRACE, f"{name} fermé · {self.action.get()} dans…")
        self._after("watch", 2000, self._watch_process)

    def _net_loop(self):
        if psutil:
            try:
                io = psutil.net_io_counters(); total = io.bytes_recv + io.bytes_sent
                if self._last_bytes is not None:
                    self.speed = max(0, total - self._last_bytes)
                self._last_bytes = total
                if hasattr(self, "speed_lbl"):
                    try: self.speed_lbl.configure(text=fmt_speed(self.speed))
                    except Exception: pass
                if self.state_ == "waiting" and self.mode.get() == "Réseau":
                    thr = to_int(self.net_thr.get(), 200) * 1024
                    need = max(1, to_int(self.net_min.get(), 3)) * 60
                    self.idle_s = self.idle_s + 1 if self.speed < thr else 0
                    sub = "Téléchargement en cours…" if not self.idle_s else "Réseau calme"
                    self._ring(fmt_speed(self.speed), sub,
                               f"inactif {fmt_hms(self.idle_s)[3:]} / {fmt_hms(need)[3:]}",
                               big=False)
                    if self.idle_s >= need:
                        self._begin_countdown(GRACE,
                                              f"{self.t['download_done']} · {self.action.get()} dans…")
            except Exception: pass
        self.after(1000, self._net_loop)

    def _recurrent_loop(self):
        try:
            if self.state_ == "idle" and self.cfg["recurrent_enabled"]:
                now = dt.datetime.now()
                hh, mm = self.cfg["recurrent_time"].split(":")
                if now.hour == int(hh) and now.minute == int(mm):
                    if idle_seconds() >= self.cfg["recurrent_idle_min"] * 60:
                        self.action.set(self.cfg["recurrent_action"])
                        self._lock(True); self._begin_countdown(GRACE, "Récurrence quotidienne")
        except Exception: pass
        self.after(60000, self._recurrent_loop)

    def _fire(self):
        self._stop_jobs(); act = self.action.get()
        self.state_ = "firing"; self._ring("00:00:00", self.t["firing"])
        self.update()
        if self.cfg.get("webhook"):
            threading.Thread(target=send_webhook, args=(self.cfg["webhook"],
                             f"[{dt.datetime.now().strftime('%H:%M')}] PC → {act}"), daemon=True).start()
        if self.scenario_queue:
            if act == "Verrouiller":
                run_action(act, self.force.get()); self.after(2000, self._next_scenario)
            else:
                run_action(act, self.force.get()); self.after(1500, self.destroy)
            return
        run_action(act, self.force.get())
        if act in ("Veille", "Verrouiller"): self.after(3000, self._cancel)
        else: self.after(1500, self.destroy)

    def _cancel(self):
        if self.state_ == "idle" and not self.jobs: return
        self._stop_jobs(); self.state_ = "idle"; self.scenario_queue = []
        self.attributes("-topmost", self.pin.get())
        self._render_extend(False); self._hide_grace_banner()
        self._lock(False); self._refresh_idle()

    def _on_close(self):
        if self.state_ != "idle" and not messagebox.askyesno(
                "Quitter ?", "Fermer annule le minuteur. Continuer ?"):
            return
        self._save(); self._shutdown()

    def _shutdown(self):
        try: self.tracker.stop()
        except Exception: pass
        if self.api_server:
            try: self.api_server.stop()
            except Exception: pass
        if hasattr(self, "tray") and self.tray:
            try: self.tray.stop()
            except Exception: pass
        self.destroy()

    # ---- API trigger ----
    def _api_trigger(self, act, secs):
        self._cancel()
        self._set_action(act, save=False)
        self._set_mode("Minuteur", save=False)
        h, r = divmod(secs, 3600); m, s = divmod(r, 60)
        self.h.set(str(h)); self.m.set(str(m)); self.s.set(str(s))
        self._show_view("timer")
        self._lock(True); self._begin_countdown(secs)

    def _start_api(self):
        try:
            self.api_server = ApiServer(self, self.cfg["api_port"], self.cfg["api_token"])
            self.api_server.start()
        except Exception: pass

    def _stop_api(self):
        if self.api_server:
            self.api_server.stop(); self.api_server = None

    # ---- Tray ----
    def _tray_setup(self):
        if not pystray or SYSTEM != "Windows": self.tray = None; return
        try:
            img = Image.new("RGB", (64, 64), self.theme["bg"])
            d = ImageDraw.Draw(img)
            d.arc([10, 14, 54, 58], start=-60, end=240, fill="white", width=6)
            d.rounded_rectangle([30, 6, 34, 30], radius=2, fill="white")
            self.tray_img = img
            menu = pystray.Menu(
                pystray.MenuItem("Afficher", self._tray_show, default=True),
                pystray.MenuItem("Annuler", lambda: self.after(0, self._cancel)),
                pystray.MenuItem("Quitter", self._tray_quit))
            self.tray = pystray.Icon("minuteur", img, "Minuteur Extinction", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
            self.after(5000, self._tray_update)
        except Exception: self.tray = None

    def _tray_update(self):
        if self.tray:
            if self.state_ == "countdown":
                rem = max(0, int(self.deadline - time.time()))
                self.tray.title = f"{fmt_hms(rem)} → {self.action.get()}"
            else:
                self.tray.title = "Minuteur Extinction"
        self.after(5000, self._tray_update)

    def _tray_show(self):
        self.after(0, lambda: (self.deiconify(), self.lift(), self.focus_force()))

    def _tray_quit(self):
        self.after(0, self._shutdown)

    # ---- Compact ----
    def toggle_compact(self):
        self.compact = not self.compact
        if self.compact: self._enter_compact()
        else: self._exit_compact()

    def _enter_compact(self):
        self._pre_compact_geom = self.geometry()
        # Masque la sidebar
        self.sidebar.grid_remove()
        # Supprime toutes les vues sauf anneau + bouton
        for w in self.content.winfo_children():
            try: w.destroy()
            except Exception: pass
        c = self.theme
        wrap = ctk.CTkFrame(self.content, fg_color=c["bg"])
        wrap.pack(fill="both", expand=True, padx=SP["md"], pady=SP["md"])
        s = self.RING
        self.canvas = tk.Canvas(wrap, width=s, height=s, bg=c["bg"], highlightthickness=0)
        self.canvas.pack(pady=SP["sm"])
        m = 12; box = (m, m, s - m, s - m)
        self.canvas.create_oval(*box, outline=c["track"], width=10)
        self.arc = self.canvas.create_arc(*box, start=90, extent=0, style="arc",
                                           width=10, outline=self._accent())
        self.t_main = self.canvas.create_text(s/2, s/2 - 8, fill=c["text"],
                                               font=(FONT, FS["display"] - 4, "bold"))
        self.t_sub = self.canvas.create_text(s/2, s/2 + 22, fill=c["muted"],
                                              font=(FONT, FS["sm"]))
        self.t_eta = self.canvas.create_text(s/2, s/2 + 42, fill=c["muted"],
                                              font=(FONT, FS["xs"]))
        self.main_btn = ctk.CTkButton(wrap, text=self.t["start"], command=self._toggle,
                                       fg_color=self._accent(), hover_color=self._accent(),
                                       text_color="#ffffff",
                                       font=ctk.CTkFont(FONT, FS["md"], "bold"),
                                       height=44, corner_radius=RADIUS["md"])
        self.main_btn.pack(fill="x", pady=(SP["sm"], 0))
        try:
            self.overrideredirect(True); self.attributes("-topmost", True)
        except Exception: pass
        self.geometry("260x340")
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<Double-Button-1>", lambda e: self.toggle_compact())
        self.canvas.create_text(self.RING / 2, self.RING - 14,
                                 text=("double-clic pour agrandir" if self.lang == "fr"
                                        else "double-click to expand"),
                                 fill=c["muted"], font=(FONT, FS["xs"] - 1, "italic"))
        self._refresh_idle()

    def _exit_compact(self):
        try:
            self.overrideredirect(False)
            self.attributes("-topmost", self.pin.get())
        except Exception: pass
        try:
            self.canvas.unbind("<ButtonPress-1>"); self.canvas.unbind("<B1-Motion>")
            self.canvas.unbind("<Double-Button-1>")
        except Exception: pass
        self.sidebar.grid()
        self._show_view(self.current_view)
        try:
            if hasattr(self, "_pre_compact_geom") and self._pre_compact_geom:
                self.geometry(self._pre_compact_geom)
        except Exception: pass

    def _drag_start(self, event):
        self._drag_dx = event.x_root - self.winfo_x()
        self._drag_dy = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        if not hasattr(self, "_drag_dx"): return
        self.geometry(f"+{event.x_root - self._drag_dx}+{event.y_root - self._drag_dy}")

    # ---- Scénario ----
    def _scn_add(self):
        if self.state_ != "idle": return
        self.scenario.append({"delay": 1800, "action": "Éteindre"})
        self._save(); self._show_view("timer")

    def _scn_del(self, i):
        if self.state_ != "idle": return
        if 0 <= i < len(self.scenario): del self.scenario[i]
        self._save(); self._show_view("timer")

    # ---- Theme ----
    def apply_theme(self, new_pref):
        self.cfg["theme"] = new_pref; save_json(CFG_PATH, self.cfg)
        is_dark = (new_pref == "auto" and detect_system_dark()) or new_pref == "dark"
        ctk.set_appearance_mode("dark" if is_dark else "light")
        self.theme = THEMES["dark" if is_dark else "light"]
        self.configure(fg_color=self.theme["bg"])
        self._style()
        self._build_shell()
        self._show_view(self.current_view)

    # ---- CLI ----
    def _apply_cli(self, a):
        if a.action: self._set_action(CLI_ACTIONS[a.action])
        if a.force: self.force.set(True)
        trigger = None
        if a.in_:
            sec = parse_duration(a.in_)
            h, r = divmod(sec, 3600); m, s = divmod(r, 60)
            self.h.set(str(h)); self.m.set(str(m)); self.s.set(str(s))
            trigger = "Minuteur"
        elif a.at:
            hh, _, mm = a.at.partition(":")
            self.ah.set(hh); self.am.set(mm or "00"); trigger = "Heure fixe"
        elif a.process:
            self.proc.set(a.process); trigger = "Processus"
        elif a.net:
            trigger = "Réseau"
        if trigger:
            self._set_mode(trigger); self._show_view("timer")
            self.after(400, self._start)


# ========= POINT D'ENTRÉE =========
def parse_args():
    p = argparse.ArgumentParser(description="Minuteur d'extinction v4")
    p.add_argument("--in", dest="in_", help="durée : 1h30m, 45m, 90s, 30 (minutes)")
    p.add_argument("--at", help="heure fixe HH:MM")
    p.add_argument("--process", help="processus à surveiller")
    p.add_argument("--net", action="store_true", help="attendre fin du téléchargement")
    p.add_argument("--action", choices=CLI_ACTIONS)
    p.add_argument("--force", action="store_true")
    return p.parse_known_args()[0]


if __name__ == "__main__":
    if SYSTEM == "Windows":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App(parse_args()).mainloop()

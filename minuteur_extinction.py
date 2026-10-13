"""
Minuteur d'extinction v3 — contrôle avancé de l'arrêt du PC.

Modes de déclenchement :
  Minuteur · Heure fixe · Processus · Réseau · Scénario (enchaîné)

Actions : Éteindre · Redémarrer · Veille · Hibernation · Verrouiller

Nouveautés v3 :
  • Statistiques : uptime quotidien/hebdo/mensuel, graphique 30 jours, top apps, batterie
  • Mode compact (fenêtre minimale) + icône dans la zone de notification
  • Notifications Windows natives · thème clair/sombre auto · FR/EN
  • Scénarios enchaînés + profils sauvegardés + programmation récurrente
  • Webhook Discord/Slack · API REST locale pour commander depuis le téléphone
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

# ========= THÈMES =========
# Tokens de design : couleurs + espacements + typo
THEMES = {
    "dark":  {"bg": "#0f1117", "card": "#181b24", "track": "#262a36",
              "border": "#2a2f3d", "hover": "#20242f",
              "text": "#e8eaf0", "muted": "#8a90a2", "warn": "#ffb547",
              "accent_soft": "#1f2330"},
    "light": {"bg": "#f4f5f8", "card": "#ffffff", "track": "#e4e7ed",
              "border": "#d9dde4", "hover": "#eef0f4",
              "text": "#1a1d26", "muted": "#6b7180", "warn": "#d58000",
              "accent_soft": "#eef1f6"},
}
# Échelle d'espacement (en pixels)
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
# Échelle typo
FS = {"xs": 9, "sm": 10, "base": 11, "md": 13, "lg": 15, "xl": 20, "display": 32}
# Rayons
RADIUS = {"sm": 6, "md": 10, "lg": 14, "pill": 999}
ACTIONS = {
    "Éteindre": "#ff5c7a", "Redémarrer": "#4da3ff", "Veille": "#b48cff",
    "Hibernation": "#39d0b3", "Verrouiller": "#8fd16a",
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
        "title": "Minuteur d'extinction", "subtitle": "Programme l'arrêt de ton PC",
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
        "proc_hint": "Se déclenche à la fermeture du processus : jeu, build, rendu, installeur…",
        "clock_hint": "Si l'heure est déjà passée, ce sera demain.",
        "warn_minute": "⚠ Plus qu'une minute !", "about_to": "{a} dans…",
        "waiting_proc": "Fermeture de", "download_done": "Téléchargement fini",
        "preset_full": "6 préréglages max. Clic droit pour en supprimer un.",
    },
    "en": {
        "title": "Shutdown Timer", "subtitle": "Schedule your PC's shutdown",
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
        "proc_hint": "Triggered when the process closes: game, build, render, installer…",
        "clock_hint": "If the time has passed, it will be tomorrow.",
        "warn_minute": "⚠ One minute left!", "about_to": "{a} in…",
        "waiting_proc": "Waiting for", "download_done": "Download finished",
        "preset_full": "Max 6 presets. Right-click one to delete it.",
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
}


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
        # purge au-delà de 90 jours
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
    """Petit serveur HTTP local. Routes :
      GET  /          — statut (JSON)
      GET  /action    — ?a=shutdown|restart|sleep|hibernate|lock|cancel&token=...&in=1800
    """

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


# ========= APPLICATION =========
class App(ctk.CTk):
    RING = 240

    def __init__(self, args):
        # Appearance CTk doit être défini avant super().__init__()
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
        self.title(self.t["title"]); self.configure(fg_color=self.theme["bg"])
        self.resizable(False, False)
        # Mapping label traduit → clé interne (actions et modes)
        self._act_label2key = dict(zip(self.t["actions"], list(ACTIONS.keys())))
        self._act_key2label = {v: k for k, v in self._act_label2key.items()}
        self._mode_label2key = dict(zip(self.t["modes"],
                                         ["Minuteur", "Heure fixe", "Processus", "Réseau", "Scénario"]))
        self._mode_key2label = {v: k for k, v in self._mode_label2key.items()}
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

        self.tracker = UsageTracker(); self.tracker.start()
        self.api_server = None
        if self.cfg["api_enabled"]:
            self._start_api()

        self._style()
        self._build()
        for v in (self.h, self.m, self.s, self.ah, self.am, self.proc, self.net_thr, self.net_min):
            v.trace_add("write", lambda *_: self._refresh_idle())
        self.attributes("-topmost", self.pin.get())
        self.bind("<Return>", lambda e: self._start() if self.state_ == "idle" else None)
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._set_mode(self.mode.get(), save=False)
        self._set_action(self.action.get(), save=False)
        self._net_loop()
        self._clock_loop()
        self._recurrent_loop()
        self._tray_setup()
        self._apply_cli(args)

    # ========= UTILITAIRES UI =========
    def _style(self):
        """Configure les styles ttk legacy (Combobox) et les options Tk globales."""
        c = self.theme
        st = ttk.Style(self); st.theme_use("clam")
        st.configure("Dark.TCombobox", fieldbackground=c["card"], background=c["card"],
                     foreground=c["text"], arrowcolor=c["text"], bordercolor=c["border"],
                     lightcolor=c["card"], darkcolor=c["card"], selectbackground=c["card"],
                     selectforeground=c["text"], padding=6)
        st.map("Dark.TCombobox", fieldbackground=[("readonly", c["card"]), ("disabled", c["card"])],
               foreground=[("disabled", c["muted"])])
        self.option_add("*TCombobox*Listbox.background", c["card"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["track"])

    def _pill(self, parent, text, cmd=None, bg=None, fg=None, size=10, bold=False,
              padx=12, pady=6, hover=True):
        """Pill en tk.Label — conservé pour compat (étapes de scénario, boutons +5/+15/+1h)."""
        c = self.theme
        bg = bg or c["card"]; fg = fg or c["text"]
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=(FONT, size, "bold" if bold else "normal"),
                     padx=padx, pady=pady, cursor="hand2")
        if cmd: b.bind("<Button-1>", lambda e: cmd())
        if hover:
            def over(e, w=b, base=bg): w.configure(bg=c["hover"] if base == c["card"] else base)
            def out(e, w=b, base=bg): w.configure(bg=base)
            b.bind("<Enter>", over); b.bind("<Leave>", out)
        return b

    def _icon_btn(self, parent, char, cmd, tooltip="", active=False):
        """Petit bouton icône carré 32x32 pour la barre de titre (pin, compact, menu)."""
        c = self.theme
        b = ctk.CTkButton(parent, text=char, width=32, height=32, corner_radius=RADIUS["md"],
                          fg_color=c["card"] if not active else c["track"],
                          hover_color=c["hover"], text_color=c["text"],
                          font=ctk.CTkFont(FONT, FS["md"]), command=cmd)
        return b

    def _spin(self, parent, var, to, width=3):
        c = self.theme
        sp = tk.Spinbox(parent, from_=0, to=to, textvariable=var, width=width, font=(FONT, 18, "bold"),
                        justify="center", bg=c["card"], fg=c["text"], buttonbackground=c["card"],
                        relief="flat", insertbackground=c["text"], wrap=True, highlightthickness=1,
                        highlightbackground=c["border"], highlightcolor=c["border"],
                        disabledbackground=c["card"], disabledforeground=c["muted"])
        self.inputs.append(sp); return sp

    def _label(self, parent, text, size=10, muted=True, **kw):
        c = self.theme
        bg = kw.pop("bg", c["bg"])
        return tk.Label(parent, text=text, bg=bg,
                        fg=c["muted"] if muted else c["text"], font=(FONT, size), **kw)

    def _card_frame(self, parent, **kw):
        """Carte arrondie CTkFrame avec padding interne."""
        c = self.theme
        f = ctk.CTkFrame(parent, fg_color=c["card"], corner_radius=RADIUS["lg"],
                         border_width=1, border_color=c["border"], **kw)
        return f

    # ========= CONSTRUCTION UI =========
    def _build(self):
        """Hiérarchie :
          1. Barre de titre mince (titre + icônes pin/compact/menu)
          2. Carte d'action primaire : « Je veux [Action ▾] »
          3. Sélecteur de mode (SegmentedButton)
          4. Panneau du mode (contenu dynamique)
          5. Anneau de progression + options (force)
          6. Récapitulatif « → à telle heure »
          7. Bouton primaire Démarrer
        """
        c = self.theme
        # Nettoyage si _build() est rappelé (ex. sortie de compact)
        if hasattr(self, "root_fr") and self.root_fr.winfo_exists():
            self.root_fr.destroy()
        self.inputs = []
        self.root_fr = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0)
        self.root_fr.pack(padx=SP["xl"], pady=SP["lg"])

        # ---- 1. Barre de titre ----
        head = ctk.CTkFrame(self.root_fr, fg_color="transparent"); head.pack(fill="x")
        tk.Label(head, text="⚡ " + self.t["title"], bg=c["bg"], fg=c["text"],
                 font=(FONT, FS["lg"], "bold")).pack(side="left")
        actions_bar = ctk.CTkFrame(head, fg_color="transparent"); actions_bar.pack(side="right")
        self.pin_btn = self._icon_btn(actions_bar, "📌", self._toggle_pin, active=self.pin.get())
        self.pin_btn.pack(side="left", padx=SP["xs"])
        self._icon_btn(actions_bar, "🗗", self.toggle_compact).pack(side="left", padx=SP["xs"])
        self._icon_btn(actions_bar, "☰", self._open_menu).pack(side="left", padx=SP["xs"])

        # ---- 2. Carte d'action primaire ----
        act_card = self._card_frame(self.root_fr)
        act_card.pack(fill="x", pady=(SP["md"], 0))
        inner = ctk.CTkFrame(act_card, fg_color="transparent")
        inner.pack(padx=SP["lg"], pady=SP["md"], fill="x")
        tk.Label(inner, text=("Je veux" if self.lang == "fr" else "I want to"),
                 bg=c["card"], fg=c["muted"], font=(FONT, FS["sm"])).pack(side="left")
        current_label = self._act_key2label[self.action.get()]
        self.action_menu = ctk.CTkOptionMenu(
            inner, values=self.t["actions"], command=self._on_action_change,
            font=ctk.CTkFont(FONT, FS["md"], "bold"),
            fg_color=self._accent(), button_color=self._accent(),
            button_hover_color=self._accent(), text_color="#ffffff",
            dropdown_fg_color=c["card"], dropdown_hover_color=c["hover"],
            dropdown_text_color=c["text"], corner_radius=RADIUS["md"], width=170, height=36)
        self.action_menu.set(current_label)
        self.action_menu.pack(side="left", padx=(SP["sm"], 0))
        self.inputs.append(self.action_menu)

        # ---- 3. Sélecteur de mode (SegmentedButton) ----
        self.mode_seg = ctk.CTkSegmentedButton(
            self.root_fr, values=self.t["modes"], command=self._on_mode_change,
            font=ctk.CTkFont(FONT, FS["sm"], "bold"),
            fg_color=c["card"], selected_color=c["track"],
            selected_hover_color=c["hover"], unselected_color=c["card"],
            unselected_hover_color=c["hover"], text_color=c["text"],
            corner_radius=RADIUS["md"], height=36)
        self.mode_seg.set(self._mode_key2label[self.mode.get()])
        self.mode_seg.pack(fill="x", pady=(SP["md"], 0))
        self.inputs.append(self.mode_seg)
        # Compat : certaines méthodes historiques itèrent sur tab_btns pour update visuel
        self.tab_btns = {}

        # ---- 4. Panneau de mode ----
        self.panel_host = ctk.CTkFrame(self.root_fr, fg_color="transparent")
        self.panel_host.pack(fill="x", pady=(SP["md"], 0))
        self.panels = {"Minuteur": self._panel_timer(), "Heure fixe": self._panel_clock(),
                       "Processus": self._panel_process(), "Réseau": self._panel_network(),
                       "Scénario": self._panel_scenario()}

        # ---- 5. Anneau de progression ----
        s = self.RING
        self.canvas = tk.Canvas(self.root_fr, width=s, height=s, bg=c["bg"], highlightthickness=0)
        self.canvas.pack(pady=(SP["md"], SP["sm"]))
        m = 14; box = (m, m, s - m, s - m)
        self.canvas.create_oval(*box, outline=c["track"], width=12)
        self.arc = self.canvas.create_arc(*box, start=90, extent=0, style="arc", width=12,
                                           outline=self._accent())
        self.t_main = self.canvas.create_text(s/2, s/2 - 10, fill=c["text"],
                                               font=(FONT, FS["display"], "bold"))
        self.t_sub = self.canvas.create_text(s/2, s/2 + 24, fill=c["muted"], font=(FONT, FS["sm"]))
        self.t_eta = self.canvas.create_text(s/2, s/2 + 44, fill=c["muted"], font=(FONT, FS["xs"]))

        # ---- Compat : act_btns est utilisé par _next_scenario/_api_trigger pour afficher l'action.
        # Comme le dropdown a remplacé les 5 pastilles, on garde un dict vide (les boucles tolèrent).
        self.act_btns = {}

        # ---- 6. Options + récap ----
        opts = ctk.CTkFrame(self.root_fr, fg_color="transparent")
        opts.pack(fill="x", pady=(SP["sm"], SP["xs"]))
        self.force_chk = ctk.CTkCheckBox(
            opts, text=self.t["force"], variable=self.force, command=self._save,
            font=ctk.CTkFont(FONT, FS["sm"]), text_color=c["muted"],
            fg_color=self._accent(), hover_color=self._accent(),
            border_color=c["border"], checkmark_color="#ffffff",
            checkbox_width=18, checkbox_height=18, corner_radius=RADIUS["sm"])
        self.force_chk.pack(side="left")

        self.recap_lbl = tk.Label(self.root_fr, text="", bg=c["bg"], fg=c["muted"],
                                   font=(FONT, FS["sm"], "italic"))
        self.recap_lbl.pack(fill="x", pady=(SP["sm"], 0))

        # Boutons d'extension (+5/+15/+1h) pendant countdown — rangée persistante
        self.extend_row = ctk.CTkFrame(self.root_fr, fg_color="transparent")
        self.extend_row.pack(fill="x")

        # ---- 7. Bouton primaire ----
        self.main_btn = ctk.CTkButton(
            self.root_fr, text=self.t["start"], command=self._toggle,
            fg_color=self._accent(), hover_color=self._accent(),
            text_color="#ffffff", font=ctk.CTkFont(FONT, FS["md"], "bold"),
            height=48, corner_radius=RADIUS["md"])
        self.main_btn.pack(fill="x", pady=(SP["sm"], SP["xs"]))

        self._update_pin()

    def _panel_timer(self):
        c = self.theme
        p = tk.Frame(self.panel_host, bg=c["bg"])
        self.presets_row = tk.Frame(p, bg=c["bg"]); self.presets_row.pack(pady=(0, 10))
        self._render_presets()
        row = tk.Frame(p, bg=c["bg"]); row.pack()
        for var, to, unit in ((self.h, 23, "h"), (self.m, 59, "min"), (self.s, 59, "s")):
            self._spin(row, var, to).pack(side="left", ipady=4)
            self._label(row, unit, 11).pack(side="left", padx=(4, 12))
        return p

    def _panel_clock(self):
        c = self.theme
        p = tk.Frame(self.panel_host, bg=c["bg"])
        row = tk.Frame(p, bg=c["bg"]); row.pack(pady=(4, 6))
        self._spin(row, self.ah, 23).pack(side="left", ipady=4)
        self._label(row, ":", 16, muted=False).pack(side="left", padx=6)
        self._spin(row, self.am, 59).pack(side="left", ipady=4)
        self._label(p, self.t["clock_hint"], 9).pack()
        return p

    def _panel_process(self):
        c = self.theme
        p = tk.Frame(self.panel_host, bg=c["bg"])
        row = tk.Frame(p, bg=c["bg"]); row.pack(fill="x")
        self.combo = ttk.Combobox(row, textvariable=self.proc, style="Dark.TCombobox",
                                  font=(FONT, 11), postcommand=self._refresh_procs)
        self.combo.pack(side="left", fill="x", expand=True); self.inputs.append(self.combo)
        self._pill(row, "↻", self._refresh_procs, size=12, padx=10, pady=3).pack(side="left", padx=(6, 0))
        self._label(p, self.t["proc_hint"], 9, wraplength=380, justify="center").pack(pady=(8, 0))
        return p

    def _panel_network(self):
        c = self.theme
        p = tk.Frame(self.panel_host, bg=c["bg"])
        row = tk.Frame(p, bg=c["bg"]); row.pack()
        self._label(row, "Sous" if self.lang == "fr" else "Below", 10).pack(side="left", padx=(0, 6))
        self._spin(row, self.net_thr, 99999, 5).pack(side="left", ipady=4)
        self._label(row, "Ko/s  pendant" if self.lang == "fr" else "KB/s  for", 10).pack(side="left", padx=6)
        self._spin(row, self.net_min, 120).pack(side="left", ipady=4)
        self._label(row, "min", 10).pack(side="left", padx=(6, 0))
        self.speed_lbl = self._label(p, "— Ko/s", 9); self.speed_lbl.pack(pady=(8, 0))
        self._label(p, self.t["net_hint"], 9).pack()
        return p

    def _panel_scenario(self):
        c = self.theme
        p = tk.Frame(self.panel_host, bg=c["bg"])
        self.scn_list = tk.Frame(p, bg=c["bg"]); self.scn_list.pack(fill="x")
        self._render_scenario()
        return p

    def _render_scenario(self):
        c = self.theme
        for w in self.scn_list.winfo_children(): w.destroy()
        for i, step in enumerate(self.scenario):
            row = tk.Frame(self.scn_list, bg=c["card"]); row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{i+1}.", bg=c["card"], fg=c["muted"],
                     font=(FONT, 10, "bold"), padx=10, pady=6).pack(side="left")
            tk.Label(row, text=f"{self.t['step_delay']} {fmt_short(step['delay'], self.lang)}",
                     bg=c["card"], fg=c["text"], font=(FONT, 10)).pack(side="left")
            tk.Label(row, text=f"→ {step['action']}", bg=c["card"],
                     fg=ACTIONS[step['action']], font=(FONT, 10, "bold"),
                     padx=10, pady=6).pack(side="left")
            self._pill(row, "✕", lambda i=i: self._scn_del(i), size=10, padx=8, pady=4,
                       fg=c["muted"]).pack(side="right", padx=4)
        add = self._pill(self.scn_list, self.t["scenario_add"], self._scn_add,
                         size=10, padx=12, pady=6); add.pack(pady=4)

    def _scn_add(self):
        if self.state_ != "idle": return
        self.scenario.append({"delay": 1800, "action": "Éteindre"})
        self._scn_edit(len(self.scenario) - 1)

    def _scn_del(self, i):
        if self.state_ != "idle" or i >= len(self.scenario): return
        del self.scenario[i]; self._render_scenario(); self._save()

    def _scn_edit(self, i):
        step = self.scenario[i]; dlg = tk.Toplevel(self); dlg.title("Étape")
        dlg.configure(bg=self.theme["bg"]); dlg.transient(self); dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="Durée (ex: 1h30m, 45m, 60)", bg=self.theme["bg"],
                 fg=self.theme["text"], font=(FONT, 10)).pack(padx=16, pady=(14, 4))
        dvar = tk.StringVar(value=fmt_short(step["delay"], "en").replace(" ", ""))
        e = tk.Entry(dlg, textvariable=dvar, bg=self.theme["card"], fg=self.theme["text"],
                     insertbackground=self.theme["text"], relief="flat", font=(FONT, 11),
                     justify="center"); e.pack(padx=16, ipady=6, fill="x")
        tk.Label(dlg, text="Action", bg=self.theme["bg"], fg=self.theme["text"],
                 font=(FONT, 10)).pack(padx=16, pady=(10, 4))
        avar = tk.StringVar(value=step["action"])
        cb = ttk.Combobox(dlg, textvariable=avar, values=list(ACTIONS.keys()),
                          state="readonly", style="Dark.TCombobox"); cb.pack(padx=16, fill="x")

        def ok():
            d = parse_duration(dvar.get())
            if d > 0:
                step["delay"] = d; step["action"] = avar.get()
                self._render_scenario(); self._save()
            dlg.destroy()
        tk.Button(dlg, text="OK", command=ok, bg=self.theme["card"], fg=self.theme["text"],
                  relief="flat", font=(FONT, 10, "bold")).pack(pady=14, padx=16, ipadx=20, fill="x")

    # ========= PRÉRÉGLAGES =========
    def _render_presets(self):
        for w in self.presets_row.winfo_children(): w.destroy()
        for sec in self.cfg["presets"]:
            b = self._pill(self.presets_row, fmt_short(sec, self.lang), lambda s=sec: self._use_preset(s))
            b.bind("<Button-3>", lambda e, s=sec: self._del_preset(s))
            b.pack(side="left", padx=3)
        self._pill(self.presets_row, "＋", self._add_preset, fg=self.theme["muted"]).pack(side="left", padx=3)

    def _hms(self):
        return to_int(self.h.get())*3600 + to_int(self.m.get())*60 + to_int(self.s.get())

    def _use_preset(self, sec):
        if self.state_ != "idle": return
        h, r = divmod(sec, 3600); m, s = divmod(r, 60)
        self.h.set(str(h)); self.m.set(str(m)); self.s.set(str(s))

    def _add_preset(self):
        sec = self._hms()
        if self.state_ != "idle" or sec <= 0 or sec in self.cfg["presets"]: return
        if len(self.cfg["presets"]) >= 6:
            return messagebox.showinfo("Préréglages", self.t["preset_full"])
        self.cfg["presets"] = sorted(self.cfg["presets"] + [sec]); self._render_presets(); self._save()

    def _del_preset(self, sec):
        if self.state_ == "idle" and sec in self.cfg["presets"]:
            self.cfg["presets"].remove(sec); self._render_presets(); self._save()

    # ========= SÉLECTIONS =========
    def _accent(self):
        return ACTIONS[self.action.get()]

    def _on_mode_change(self, label):
        key = self._mode_label2key.get(label, label)
        self._set_mode(key)

    def _on_action_change(self, label):
        key = self._act_label2key.get(label, label)
        self._set_action(key)

    def _set_mode(self, name, save=True):
        if self.state_ != "idle": return
        self.mode.set(name)
        if hasattr(self, "mode_seg"):
            lbl = self._mode_key2label.get(name, name)
            if self.mode_seg.get() != lbl:
                self.mode_seg.set(lbl)
        for n, p in self.panels.items(): p.pack_forget()
        self.panels[name].pack(fill="x")
        if name == "Processus": self._refresh_procs()
        self._refresh_idle()
        if save: self._save()

    def _set_action(self, name, save=True):
        if self.state_ != "idle": return
        self.action.set(name)
        accent = self._accent()
        if hasattr(self, "action_menu"):
            lbl = self._act_key2label.get(name, name)
            if self.action_menu.get() != lbl:
                self.action_menu.set(lbl)
            self.action_menu.configure(fg_color=accent, button_color=accent,
                                        button_hover_color=accent)
        if hasattr(self, "canvas"):
            self.canvas.itemconfigure(self.arc, outline=accent)
        if hasattr(self, "main_btn"):
            self.main_btn.configure(fg_color=accent, hover_color=accent)
        if hasattr(self, "force_chk"):
            self.force_chk.configure(fg_color=accent, hover_color=accent)
        self._refresh_idle()
        if save: self._save()

    def _toggle_pin(self):
        self.pin.set(not self.pin.get())
        self.attributes("-topmost", self.pin.get())
        self._update_pin(); self._save()

    def _update_pin(self):
        c = self.theme
        self.pin_btn.configure(fg_color=c["track"] if self.pin.get() else c["card"])

    def _open_menu(self):
        """Menu contextuel regroupant Stats / Profils / Paramètres."""
        c = self.theme
        m = tk.Menu(self, tearoff=0, bg=c["card"], fg=c["text"],
                    activebackground=c["hover"], activeforeground=c["text"],
                    bd=0, relief="flat", font=(FONT, FS["sm"]))
        m.add_command(label="📊  " + self.t["stats"], command=self.open_stats)
        m.add_command(label="💾  " + self.t["profiles"], command=self.open_profiles)
        m.add_command(label="⚙  " + self.t["settings"], command=self.open_settings)
        try:
            x = self.winfo_pointerx(); y = self.winfo_pointery()
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _refresh_procs(self):
        try: self.combo["values"] = list_processes()
        except Exception: pass

    def _save(self):
        self.cfg.update(
            last_action=self.action.get(), last_mode=self.mode.get(),
            force=self.force.get(), pin=self.pin.get(),
            last_process=self.proc.get().strip(),
            net_threshold=to_int(self.net_thr.get(), 200),
            net_minutes=to_int(self.net_min.get(), 3), scenario=self.scenario,
            lang=self.lang)
        save_json(CFG_PATH, self.cfg)

    # ========= AFFICHAGE =========
    def _ring(self, main, sub="", eta="", big=True):
        c = self.canvas
        c.itemconfigure(self.t_main, text=main, font=(FONT, 32 if big else 20, "bold"))
        c.itemconfigure(self.t_sub, text=sub)
        c.itemconfigure(self.t_eta, text=eta)

    def _secs_until_clock(self):
        now = dt.datetime.now()
        target = now.replace(hour=min(to_int(self.ah.get()), 23),
                             minute=min(to_int(self.am.get()), 59), second=0, microsecond=0)
        if target <= now: target += dt.timedelta(days=1)
        return int((target - now).total_seconds()), target

    def _refresh_idle(self):
        if self.state_ != "idle": return
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
            day = "demain " if (self.lang == "fr" and target.date() > dt.date.today()) else \
                  ("tomorrow " if target.date() > dt.date.today() else "")
            self._ring(target.strftime("%H:%M"), f"{act} {day}à cette heure" if self.lang == "fr"
                       else f"{act} {day}at this time", f"dans {fmt_short(sec, self.lang)}"
                       if self.lang == "fr" else f"in {fmt_short(sec, self.lang)}")
            self.canvas.itemconfigure(self.arc, extent=-359.9)
        elif mode == "Processus":
            name = self.proc.get().strip() or "..."
            self._ring("…", f"{act} — {self.t['waiting_proc']}", name, big=False)
            self.canvas.itemconfigure(self.arc, extent=-90)
        elif mode == "Réseau":
            self._ring("Réseau", f"{act} quand débit <",
                       f"{to_int(self.net_thr.get())} Ko/s / {to_int(self.net_min.get())} min", big=False)
            self.canvas.itemconfigure(self.arc, extent=-90)
        else:  # Scénario
            total = sum(st["delay"] for st in self.scenario)
            self._ring(f"{len(self.scenario)} étapes" if self.lang == "fr" else f"{len(self.scenario)} steps",
                       "Chaîne d'actions" if self.lang == "fr" else "Action chain",
                       f"total {fmt_short(total, self.lang)}", big=False)
            self.canvas.itemconfigure(self.arc, extent=-359.9)
        # Récapitulatif dynamique au-dessus du bouton Démarrer
        if hasattr(self, "recap_lbl"):
            self.recap_lbl.configure(text=self._build_recap())

    def _build_recap(self):
        """Phrase récapitulative affichée au-dessus du bouton Démarrer."""
        act, mode, lang = self.action.get(), self.mode.get(), self.lang
        if mode == "Minuteur":
            sec = self._hms()
            if sec <= 0:
                return ("Choisis une durée pour voir le récapitulatif."
                        if lang == "fr" else "Pick a duration to preview.")
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
            return (f"→ {act} quand le débit chute sous {to_int(self.net_thr.get())} Ko/s "
                    f"pendant {to_int(self.net_min.get())} min" if lang == "fr"
                    else f"→ {act} when speed stays below {to_int(self.net_thr.get())} KB/s "
                    f"for {to_int(self.net_min.get())} min")
        # Scénario
        total = sum(st["delay"] for st in self.scenario)
        return (f"→ {len(self.scenario)} étapes, durée totale {fmt_short(total, lang)}"
                if lang == "fr"
                else f"→ {len(self.scenario)} steps, total {fmt_short(total, lang)}")

    def _clock_loop(self):
        if self.state_ == "idle" and self.mode.get() in ("Minuteur", "Heure fixe"):
            self._refresh_idle()
        self.after(15000, self._clock_loop)

    # ========= PLANIFICATION =========
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

    def _start(self):
        if self.state_ != "idle": return
        mode = self.mode.get()
        if mode == "Minuteur":
            sec = self._hms()
            if sec <= 0: return messagebox.showwarning("Durée", "Choisis une durée > 0.")
            self._lock(True); self._begin_countdown(sec)
        elif mode == "Heure fixe":
            self._lock(True); self._begin_countdown(self._secs_until_clock()[0])
        elif mode == "Processus":
            name = self.proc.get().strip()
            if not name: return messagebox.showwarning("Processus", "Choisis un processus.")
            if not is_running(name): return messagebox.showwarning("Processus", f"« {name} » n'est pas en cours.")
            self._lock(True); self.state_ = "waiting"; self._watch_process(); self._spinner()
        elif mode == "Réseau":
            if not psutil: return messagebox.showerror("Réseau", "psutil manquant.")
            self._lock(True); self.state_ = "waiting"; self.idle_s = 0; self._spinner()
        else:
            if not self.scenario: return messagebox.showwarning("Scénario", "Aucune étape.")
            self._lock(True); self.scenario_queue = list(self.scenario); self._next_scenario()
        self._save()

    def _next_scenario(self):
        if not self.scenario_queue:
            self.state_ = "idle"; self._lock(False); self._refresh_idle(); return
        step = self.scenario_queue.pop(0)
        # Mise à jour visuelle de l'action sans toucher au verrou (bypass _set_action qui l'exige idle)
        self.action.set(step["action"])
        accent = self._accent()
        if hasattr(self, "action_menu"):
            self.action_menu.set(self._act_key2label.get(step["action"], step["action"]))
            self.action_menu.configure(fg_color=accent, button_color=accent,
                                        button_hover_color=accent)
        self.canvas.itemconfigure(self.arc, outline=accent)
        self.main_btn.configure(fg_color=self.theme["track"], hover_color=self.theme["hover"])
        self._begin_countdown(step["delay"], reason=f"Étape · {step['action']}")

    def _lock(self, locked):
        for w in self.inputs:
            try: w.configure(state="disabled" if locked else "normal")
            except tk.TclError: pass
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
        self._render_extend(True); self._tick()

    def _render_extend(self, show):
        for w in self.extend_row.winfo_children(): w.destroy()
        if not show: return
        inner = tk.Frame(self.extend_row, bg=self.theme["bg"]); inner.pack()
        for label, sec in (("+5 min", 300), ("+15 min", 900), ("+1 h", 3600)):
            self._pill(inner, label, lambda s=sec: self._extend(s), size=9).pack(side="left", padx=3)

    def _extend(self, sec):
        if self.state_ != "countdown": return
        self.deadline += sec; self.total += sec; self.warned = False
        self.attributes("-topmost", self.pin.get())
        self.canvas.itemconfigure(self.arc, outline=self._accent())

    def _tick(self):
        rem = max(0.0, self.deadline - time.time()); shown = math.ceil(rem)
        end = dt.datetime.fromtimestamp(self.deadline).strftime("%H:%M:%S")
        sub = self.reason or self.t["about_to"].format(a=self.action.get())
        self._ring(fmt_hms(shown), sub, f"→ {end}")
        self.canvas.itemconfigure(self.arc, start=90, extent=-359.9 * rem / max(self.total, 1))

        if rem <= 60 and not self.warned:
            self.warned = True
            self.canvas.itemconfigure(self.arc, outline=self.theme["warn"])
            self.deiconify(); self.attributes("-topmost", True); self.lift(); beep()
            if self.cfg["notify"]:
                notify(self.t["title"], self.t["warn_minute"] + f" ({self.action.get()})")

        if rem <= 0: return self._fire()
        self._after("tick", 200, self._tick)

    def _spinner(self):
        if self.state_ != "waiting": return
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
                    self.speed_lbl.configure(text=fmt_speed(self.speed))
                if self.state_ == "waiting" and self.mode.get() == "Réseau":
                    thr = to_int(self.net_thr.get(), 200) * 1024
                    need = max(1, to_int(self.net_min.get(), 3)) * 60
                    self.idle_s = self.idle_s + 1 if self.speed < thr else 0
                    sub = "Téléchargement en cours…" if not self.idle_s else "Réseau calme"
                    self._ring(fmt_speed(self.speed), sub,
                               f"inactif {fmt_hms(self.idle_s)[3:]} / {fmt_hms(need)[3:]}", big=False)
                    if self.idle_s >= need:
                        self._begin_countdown(GRACE,
                                              f"{self.t['download_done']} · {self.action.get()} dans…")
            except Exception:
                pass
        self.after(1000, self._net_loop)

    def _recurrent_loop(self):
        """Tous les jours à HH:MM, si PC inactif depuis N min → action."""
        try:
            if self.state_ == "idle" and self.cfg["recurrent_enabled"]:
                now = dt.datetime.now()
                hh, mm = self.cfg["recurrent_time"].split(":")
                if now.hour == int(hh) and now.minute == int(mm):
                    if idle_seconds() >= self.cfg["recurrent_idle_min"] * 60:
                        self.action.set(self.cfg["recurrent_action"])
                        self._lock(True); self._begin_countdown(GRACE,
                                                                "Récurrence quotidienne")
        except Exception:
            pass
        self.after(60000, self._recurrent_loop)

    def _fire(self):
        self._stop_jobs(); act = self.action.get()
        self.state_ = "firing"; self._ring("00:00:00", self.t["firing"])
        self.update()
        if self.cfg.get("webhook"):
            threading.Thread(target=send_webhook, args=(self.cfg["webhook"],
                             f"[{dt.datetime.now().strftime('%H:%M')}] PC → {act}"), daemon=True).start()
        if self.scenario_queue:
            run_action(act, self.force.get()) if act in ("Verrouiller",) else None
            if act == "Verrouiller":
                self.after(2000, self._next_scenario)
            else:
                run_action(act, self.force.get())
                self.after(1500, self.destroy)
            return
        run_action(act, self.force.get())
        if act in ("Veille", "Verrouiller"): self.after(3000, self._cancel)
        else: self.after(1500, self.destroy)

    def _cancel(self):
        if self.state_ == "idle" and not self.jobs: return
        self._stop_jobs(); self.state_ = "idle"; self.scenario_queue = []
        self.attributes("-topmost", self.pin.get())
        self._render_extend(False); self._lock(False); self._refresh_idle()

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

    # ========= API =========
    def _api_trigger(self, act, secs):
        self._cancel()
        self._set_action(act, save=False)
        self._set_mode("Minuteur", save=False)
        h, r = divmod(secs, 3600); m, s = divmod(r, 60)
        self.h.set(str(h)); self.m.set(str(m)); self.s.set(str(s))
        self._lock(True); self._begin_countdown(secs)

    def _start_api(self):
        try:
            self.api_server = ApiServer(self, self.cfg["api_port"], self.cfg["api_token"])
            self.api_server.start()
        except Exception:
            pass

    def _stop_api(self):
        if self.api_server:
            self.api_server.stop(); self.api_server = None

    # ========= TRAY =========
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
        except Exception:
            self.tray = None

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

    # ========= FENÊTRES SECONDAIRES =========
    def toggle_compact(self):
        """Mode compact : ne garde que l'anneau + bouton primaire + récap."""
        self.compact = not self.compact
        keep = {self.canvas, self.main_btn, self.recap_lbl, self.extend_row}
        for w in self.root_fr.winfo_children():
            if w in keep:
                continue
            if self.compact:
                w.pack_forget()
            else:
                # Repack dans l'ordre : rebuild complet est plus fiable
                pass
        if not self.compact:
            self._build()

    def open_stats(self):
        StatsWindow(self)

    def open_settings(self):
        SettingsWindow(self)

    def open_profiles(self):
        ProfilesWindow(self)

    # ========= CLI =========
    def _apply_cli(self, a):
        if a.action: self._set_action(CLI_ACTIONS[a.action])
        if a.force: self.force.set(True)
        trigger = None
        if a.in_:
            sec = parse_duration(a.in_)
            h, r = divmod(sec, 3600); m, s = divmod(r, 60)
            self.h.set(str(h)); self.m.set(str(m)); self.s.set(str(s)); trigger = "Minuteur"
        elif a.at:
            hh, _, mm = a.at.partition(":")
            self.ah.set(hh); self.am.set(mm or "00"); trigger = "Heure fixe"
        elif a.process:
            self.proc.set(a.process); trigger = "Processus"
        elif a.net:
            trigger = "Réseau"
        if trigger:
            self._set_mode(trigger); self.after(400, self._start)


# ========= FENÊTRES SECONDAIRES =========
class StatsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent); self.app = parent; self.c = parent.theme
        self.title(parent.t["stats"]); self.configure(bg=self.c["bg"]); self.resizable(False, False)
        self.transient(parent); self._build()

    def _card(self, parent, label, value, color=None):
        c = self.c
        f = tk.Frame(parent, bg=c["card"])
        tk.Label(f, text=label, bg=c["card"], fg=c["muted"], font=(FONT, 9)).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(f, text=value, bg=c["card"], fg=color or c["text"],
                 font=(FONT, 18, "bold")).pack(anchor="w", padx=12, pady=(0, 12))
        return f

    def _build(self):
        c = self.c; t = self.app.tracker; lang = self.app.lang
        wrap = tk.Frame(self, bg=c["bg"], padx=18, pady=16); wrap.pack()

        row = tk.Frame(wrap, bg=c["bg"]); row.pack(fill="x", pady=(0, 8))
        self._card(row, self.app.t["today"], fmt_duration_long(t.uptime_today(), lang)).pack(side="left", expand=True, fill="x", padx=3)
        self._card(row, self.app.t["week"], fmt_duration_long(t.uptime_range(7), lang)).pack(side="left", expand=True, fill="x", padx=3)
        self._card(row, self.app.t["month"], fmt_duration_long(t.uptime_range(30), lang)).pack(side="left", expand=True, fill="x", padx=3)

        first, last = t.first_last_today()
        row2 = tk.Frame(wrap, bg=c["bg"]); row2.pack(fill="x", pady=(0, 8))
        self._card(row2, self.app.t["first_boot"], first or "—").pack(side="left", expand=True, fill="x", padx=3)
        self._card(row2, self.app.t["last_off"], last or "—").pack(side="left", expand=True, fill="x", padx=3)
        avg = t.uptime_range(30) // 30
        self._card(row2, self.app.t["avg_daily"], fmt_duration_long(avg, lang)).pack(side="left", expand=True, fill="x", padx=3)

        # graphique 30j
        series = t.daily_series(30)
        tk.Label(wrap, text="30 " + ("derniers jours" if lang == "fr" else "last days"),
                 bg=c["bg"], fg=c["muted"], font=(FONT, 10)).pack(anchor="w", pady=(10, 4))
        gw, gh = 540, 110
        g = tk.Canvas(wrap, width=gw, height=gh, bg=c["card"], highlightthickness=0); g.pack()
        peak = max((v for _, v in series), default=1) or 1
        bw = gw / len(series)
        for i, (_, v) in enumerate(series):
            x = i * bw + bw * 0.1; h = (v / peak) * (gh - 20)
            g.create_rectangle(x, gh - 10 - h, x + bw * 0.8, gh - 10,
                               fill="#ff5c7a" if v else c["track"], outline="")
        g.create_text(6, 10, text=fmt_duration_long(peak, lang), anchor="nw", fill=c["muted"], font=(FONT, 8))

        # top apps
        tk.Label(wrap, text=self.app.t["top_apps"], bg=c["bg"], fg=c["muted"],
                 font=(FONT, 10)).pack(anchor="w", pady=(14, 4))
        top = t.top_apps(5, 7); mx = max((v for _, v in top), default=1) or 1
        tbox = tk.Frame(wrap, bg=c["bg"]); tbox.pack(fill="x")
        for name, sec in top:
            r = tk.Frame(tbox, bg=c["bg"]); r.pack(fill="x", pady=2)
            tk.Label(r, text=name, bg=c["bg"], fg=c["text"], font=(FONT, 9),
                     width=24, anchor="w").pack(side="left")
            bar = tk.Frame(r, bg=c["card"], height=14); bar.pack(side="left", fill="x", expand=True)
            fill = tk.Frame(bar, bg="#4da3ff", height=14)
            fill.place(x=0, y=0, relwidth=sec / mx, relheight=1)
            tk.Label(r, text=fmt_duration_long(sec, lang), bg=c["bg"], fg=c["muted"],
                     font=(FONT, 9), width=10, anchor="e").pack(side="right")
        if not top:
            tk.Label(tbox, text="Pas encore de données." if lang == "fr" else "No data yet.",
                     bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(pady=6)

        # batterie
        b = battery_info()
        tk.Label(wrap, text=self.app.t["battery"], bg=c["bg"], fg=c["muted"],
                 font=(FONT, 10)).pack(anchor="w", pady=(14, 4))
        if b["present"]:
            txt = f"{b['percent']} % — "
            txt += self.app.t["charging"] if b["plugged"] else \
                   ("sur batterie" if lang == "fr" else "on battery")
            if b["autonomy"]:
                txt += f"  ·  ~ {fmt_duration_long(b['autonomy'], lang)}"
        else:
            txt = "PC fixe (pas de batterie détectée)" if lang == "fr" else "No battery detected"
        tk.Label(wrap, text=txt, bg=c["bg"], fg=c["text"], font=(FONT, 11)).pack(anchor="w")


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent); self.app = parent; self.c = parent.theme
        self.title(parent.t["settings"]); self.configure(bg=self.c["bg"]); self.resizable(False, False)
        self.transient(parent); self._build()

    def _section(self, parent, title):
        c = self.c
        tk.Label(parent, text=title, bg=c["bg"], fg=c["text"],
                 font=(FONT, 11, "bold")).pack(anchor="w", pady=(10, 4))

    def _row(self, parent, label):
        c = self.c
        r = tk.Frame(parent, bg=c["bg"]); r.pack(fill="x", pady=3)
        tk.Label(r, text=label, bg=c["bg"], fg=c["muted"], font=(FONT, 10),
                 width=22, anchor="w").pack(side="left")
        return r

    def _build(self):
        c = self.c; cfg = self.app.cfg
        wrap = tk.Frame(self, bg=c["bg"], padx=18, pady=16); wrap.pack(fill="x")

        self._section(wrap, "Apparence")
        r = self._row(wrap, "Langue / Language")
        lv = tk.StringVar(value=cfg["lang"])
        for code in ("fr", "en"):
            tk.Radiobutton(r, text=code.upper(), variable=lv, value=code,
                           bg=c["bg"], fg=c["text"], selectcolor=c["card"],
                           activebackground=c["bg"], activeforeground=c["text"],
                           font=(FONT, 9), bd=0, highlightthickness=0,
                           command=lambda v=lv: self._lang(v.get())).pack(side="left", padx=4)
        r = self._row(wrap, "Thème")
        tv = tk.StringVar(value=cfg["theme"])
        for code, label in (("auto", "Auto"), ("dark", "Sombre"), ("light", "Clair")):
            tk.Radiobutton(r, text=label, variable=tv, value=code,
                           bg=c["bg"], fg=c["text"], selectcolor=c["card"],
                           activebackground=c["bg"], activeforeground=c["text"],
                           font=(FONT, 9), bd=0, highlightthickness=0,
                           command=lambda v=tv: self._theme(v.get())).pack(side="left", padx=4)

        self._section(wrap, "Notifications")
        nv = tk.BooleanVar(value=cfg["notify"])
        tk.Checkbutton(wrap, text="Notifications Windows natives", variable=nv,
                       command=lambda: self._set("notify", nv.get()),
                       bg=c["bg"], fg=c["text"], selectcolor=c["card"],
                       activebackground=c["bg"], activeforeground=c["text"],
                       font=(FONT, 9), bd=0, highlightthickness=0).pack(anchor="w")

        self._section(wrap, "Récurrence quotidienne")
        rv = tk.BooleanVar(value=cfg["recurrent_enabled"])
        tk.Checkbutton(wrap, text="Chaque jour, si inactif depuis N min →",
                       variable=rv, command=lambda: self._set("recurrent_enabled", rv.get()),
                       bg=c["bg"], fg=c["text"], selectcolor=c["card"],
                       activebackground=c["bg"], activeforeground=c["text"],
                       font=(FONT, 9), bd=0, highlightthickness=0).pack(anchor="w")
        rr = tk.Frame(wrap, bg=c["bg"]); rr.pack(fill="x", pady=4)
        tk.Label(rr, text="  Heure", bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(side="left")
        hv = tk.StringVar(value=cfg["recurrent_time"])
        e = tk.Entry(rr, textvariable=hv, width=6, bg=c["card"], fg=c["text"], relief="flat",
                     insertbackground=c["text"], font=(FONT, 10), justify="center")
        e.pack(side="left", padx=4, ipady=3)
        hv.trace_add("write", lambda *_: self._set("recurrent_time", hv.get()))
        tk.Label(rr, text="  Inactif min", bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(side="left")
        iv = tk.StringVar(value=str(cfg["recurrent_idle_min"]))
        tk.Entry(rr, textvariable=iv, width=4, bg=c["card"], fg=c["text"], relief="flat",
                 insertbackground=c["text"], font=(FONT, 10), justify="center").pack(side="left", padx=4, ipady=3)
        iv.trace_add("write", lambda *_: self._set("recurrent_idle_min", to_int(iv.get(), 15)))
        tk.Label(rr, text="  Action", bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(side="left")
        av = tk.StringVar(value=cfg["recurrent_action"])
        cb = ttk.Combobox(rr, textvariable=av, values=list(ACTIONS.keys()),
                          state="readonly", width=12, style="Dark.TCombobox")
        cb.pack(side="left", padx=4)
        av.trace_add("write", lambda *_: self._set("recurrent_action", av.get()))

        self._section(wrap, "Webhook (Discord / Slack)")
        wv = tk.StringVar(value=cfg["webhook"])
        tk.Entry(wrap, textvariable=wv, bg=c["card"], fg=c["text"], relief="flat",
                 insertbackground=c["text"], font=(FONT, 9)).pack(fill="x", ipady=5)
        wv.trace_add("write", lambda *_: self._set("webhook", wv.get().strip()))
        tk.Label(wrap, text="URL postée après chaque action (vide = désactivé).",
                 bg=c["bg"], fg=c["muted"], font=(FONT, 8)).pack(anchor="w", pady=(2, 0))

        self._section(wrap, "API REST locale (contrôle depuis le téléphone)")
        av2 = tk.BooleanVar(value=cfg["api_enabled"])
        tk.Checkbutton(wrap, text=f"Serveur HTTP activé (port {cfg['api_port']})",
                       variable=av2, command=lambda: self._api(av2.get()),
                       bg=c["bg"], fg=c["text"], selectcolor=c["card"],
                       activebackground=c["bg"], activeforeground=c["text"],
                       font=(FONT, 9), bd=0, highlightthickness=0).pack(anchor="w")
        ip = lan_ip()
        url = f"http://{ip}:{cfg['api_port']}/action?a=shutdown&in=1800&token={cfg['api_token']}"
        tk.Label(wrap, text="Exemple :", bg=c["bg"], fg=c["muted"],
                 font=(FONT, 8)).pack(anchor="w", pady=(4, 0))
        urlbox = tk.Entry(wrap, bg=c["card"], fg=c["text"], relief="flat",
                          font=(FONT, 8), readonlybackground=c["card"])
        urlbox.insert(0, url); urlbox.configure(state="readonly")
        urlbox.pack(fill="x", ipady=4, pady=2)
        tk.Label(wrap,
                 text="Actions : shutdown · restart · sleep · hibernate · lock · cancel  |  in=sec (défaut 1)",
                 bg=c["bg"], fg=c["muted"], font=(FONT, 8), wraplength=460,
                 justify="left").pack(anchor="w")

    def _set(self, k, v):
        self.app.cfg[k] = v; save_json(CFG_PATH, self.app.cfg)

    def _lang(self, v):
        if v == self.app.lang: return
        self._set("lang", v); self.app.lang = v; self.app.t = I18N[v]
        messagebox.showinfo("Langue", "Relance l'application pour appliquer la langue.")

    def _theme(self, v):
        self._set("theme", v)
        messagebox.showinfo("Thème", "Relance l'application pour appliquer le thème.")

    def _api(self, enabled):
        self._set("api_enabled", enabled)
        if enabled: self.app._start_api()
        else: self.app._stop_api()


class ProfilesWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent); self.app = parent; self.c = parent.theme
        self.title(parent.t["profiles"]); self.configure(bg=self.c["bg"])
        self.resizable(False, False); self.transient(parent); self._build()

    def _build(self):
        c = self.c; wrap = tk.Frame(self, bg=c["bg"], padx=18, pady=14); wrap.pack(fill="x")
        tk.Label(wrap, text="Profils enregistrés", bg=c["bg"], fg=c["text"],
                 font=(FONT, 12, "bold")).pack(anchor="w", pady=(0, 8))

        self.list_fr = tk.Frame(wrap, bg=c["bg"]); self.list_fr.pack(fill="x")
        self._render()

        row = tk.Frame(wrap, bg=c["bg"]); row.pack(pady=(10, 0))
        self.app._pill(row, self.app.t["add_profile"], self._add, size=10).pack(side="left", padx=4)

    def _render(self):
        c = self.c
        for w in self.list_fr.winfo_children(): w.destroy()
        if not self.app.profiles:
            tk.Label(self.list_fr, text="Aucun profil pour le moment.",
                     bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(pady=4)
            return
        for i, pr in enumerate(self.app.profiles):
            r = tk.Frame(self.list_fr, bg=c["card"]); r.pack(fill="x", pady=2)
            tk.Label(r, text=pr["name"], bg=c["card"], fg=c["text"],
                     font=(FONT, 10, "bold"), padx=12, pady=8).pack(side="left")
            tk.Label(r, text=f"{pr['mode']} → {pr['action']}", bg=c["card"],
                     fg=c["muted"], font=(FONT, 9)).pack(side="left")
            self.app._pill(r, "Charger", lambda p=pr: self._load(p),
                           size=9, padx=10, pady=4).pack(side="right", padx=3)
            self.app._pill(r, "✕", lambda i=i: self._del(i), size=10, padx=8, pady=4,
                           fg=c["muted"]).pack(side="right", padx=3)

    def _add(self):
        name = simpledialog.askstring("Nouveau profil", "Nom du profil :", parent=self)
        if not name: return
        self.app.profiles.append({
            "name": name, "mode": self.app.mode.get(), "action": self.app.action.get(),
            "h": self.app.h.get(), "m": self.app.m.get(), "s": self.app.s.get(),
            "ah": self.app.ah.get(), "am": self.app.am.get(),
            "process": self.app.proc.get(), "net_thr": self.app.net_thr.get(),
            "net_min": self.app.net_min.get(),
            "scenario": [dict(st) for st in self.app.scenario],
        })
        save_json(PROFILES_PATH, self.app.profiles); self._render()

    def _del(self, i):
        del self.app.profiles[i]; save_json(PROFILES_PATH, self.app.profiles); self._render()

    def _load(self, pr):
        self.app._cancel()
        self.app._set_action(pr["action"]); self.app._set_mode(pr["mode"])
        self.app.h.set(pr["h"]); self.app.m.set(pr["m"]); self.app.s.set(pr["s"])
        self.app.ah.set(pr["ah"]); self.app.am.set(pr["am"])
        self.app.proc.set(pr["process"]); self.app.net_thr.set(pr["net_thr"])
        self.app.net_min.set(pr["net_min"])
        self.app.scenario = [dict(st) for st in pr.get("scenario", [])]
        if hasattr(self.app, "scn_list"): self.app._render_scenario()
        self.destroy()


# ========= POINT D'ENTRÉE =========
def parse_args():
    p = argparse.ArgumentParser(description="Minuteur d'extinction v3")
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

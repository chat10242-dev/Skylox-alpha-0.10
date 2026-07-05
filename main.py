#!/usr/bin/env python3
# Skylox Alpha — main.py
# Pseudo-multiplayer avanzato, editor ruoli/input/abilità, spettatore, IA, login, engine, share play

import os
import json
import time
import hashlib
import socket
import threading
import subprocess
import random
import tkinter as tk
from tkinter import filedialog
import dearpygui.dearpygui as dpg

# ---------------- PATH & DATA ----------------

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "skylox_data")

USERS_FILE    = os.path.join(DATA_DIR, "users.json")
GAMES_FILE    = os.path.join(DATA_DIR, "games.json")
CHAT_FILE     = os.path.join(DATA_DIR, "chat.json")
FEED_FILE     = os.path.join(DATA_DIR, "feed.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
ENGINE_FILE   = os.path.join(DATA_DIR, "engine.json")

def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------------- GLOBAL STATE ----------------

users      = []
games      = []
chat       = []
feed       = []
settings   = {}
accounts   = []
engine     = None

current_user = None

THEMES = ["dark", "light", "system"]
CURRENT_THEME = "system"

LANGUAGES = ["Italiano", "English", "Español"]
CURRENT_LANGUAGE = "Italiano"

CONTROLLER_MODES = ["Keyboard/Mouse", "Gamepad", "DualSense", "Xbox Controller"]
CURRENT_CONTROLLER = "Keyboard/Mouse"

PERFORMANCE_MODES = ["Low", "Medium", "High"]
CURRENT_PERFORMANCE = "Medium"

PSEUDO_MP_GLOBAL_ENABLED = False

share_conn = None
ia_thread = None
ia_running = False

# ---------------- LOGIN ----------------

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def find_user(username):
    for u in users:
        if u["username"].lower() == username.lower():
            return u
    return None

def update_pw_strength(sender, app_data, user_data):
    pw = dpg.get_value("login_password")
    score = 0
    if len(pw) >= 8: score += 1
    if any(c.islower() for c in pw): score += 1
    if any(c.isupper() for c in pw): score += 1
    if any(c.isdigit() for c in pw): score += 1
    if any(c in "!@#$%^&*()-_=+[]{};:,.<>?/\\|" for c in pw): score += 1
    strength = ["Debole", "Media", "Forte"][min(score-1, 2)] if score else "Debole"
    dpg.set_value("pw_strength_label", f"Forza password: {strength}")

def link_account(user):
    if user["username"] not in [a["username"] for a in accounts]:
        accounts.append({"username": user["username"]})
        save_json(ACCOUNTS_FILE, accounts)

def unlink_account(username):
    global accounts
    accounts = [a for a in accounts if a["username"] != username]
    save_json(ACCOUNTS_FILE, accounts)

def on_login(sender, app_data, user_data):
    global current_user
    username = dpg.get_value("login_username").strip()
    password = dpg.get_value("login_password")

    if not username or not password:
        add_feed("Inserisci username e password.")
        return

    user = find_user(username)
    pw_hash = hash_password(password)

    if user is None:
        user = {
            "username": username,
            "password_hash": pw_hash,
            "friends": [],
            "friend_requests": [],
            "blocked_users": []
        }
        users.append(user)
        save_json(USERS_FILE, users)
        add_feed(f"Nuovo utente creato: {username}")
    else:
        if user["password_hash"] != pw_hash:
            add_feed("Password errata.")
            return

    current_user = user
    link_account(user)
    add_feed(f"Login come {username}")

    dpg.hide_item("login_window")
    dpg.show_item("console_ui_root")

    refresh_all_ui()

def auto_login():
    global current_user
    if not accounts:
        return
    for acc in accounts:
        u = find_user(acc["username"])
        if u:
            current_user = u
            add_feed(f"Login automatico come {u['username']}")
            dpg.hide_item("login_window")
            dpg.show_item("console_ui_root")
            refresh_all_ui()
            return

def logout(sender, app_data, user_data):
    global current_user
    if current_user:
        add_feed(f"Disconnesso da {current_user['username']}")
    current_user = None
    dpg.show_item("login_window")
    dpg.hide_item("console_ui_root")
    refresh_account_list()

def exit_account(sender, app_data, user_data):
    global current_user
    if current_user:
        unlink_account(current_user["username"])
        add_feed(f"Account {current_user['username']} rimosso dal dispositivo.")
    current_user = None
    dpg.show_item("login_window")
    dpg.hide_item("console_ui_root")
    refresh_account_list()

def switch_account(sender, app_data, user_data):
    global current_user
    add_feed("Cambio account.")
    current_user = None
    dpg.show_item("login_window")
    dpg.hide_item("console_ui_root")

def refresh_account_list():
    if not dpg.does_item_exist("accounts_list"):
        return
    dpg.delete_item("accounts_list", children_only=True)
    dpg.add_text("Account collegati:", parent="accounts_list")
    if not accounts:
        dpg.add_text("Nessun account.", parent="accounts_list")
        return
    for acc in accounts:
        dpg.add_text(f"• {acc['username']}", parent="accounts_list")

# ---------------- FEED ----------------

def add_feed(text):
    feed.append({"timestamp": time.time(), "text": text})
    save_json(FEED_FILE, feed)
    if dpg.does_item_exist("feed_list"):
        dpg.delete_item("feed_list", children_only=True)
        for e in feed[-50:]:
            dpg.add_text(f"[{time.strftime('%H:%M:%S', time.localtime(e['timestamp']))}] {e['text']}",
                         parent="feed_list")

# ---------------- CHAT ----------------

def refresh_chat():
    if not dpg.does_item_exist("chat_list"):
        return
    dpg.delete_item("chat_list", children_only=True)
    for m in chat[-100:]:
        color = (0, 200, 255) if current_user and m["author"] == current_user["username"] else (200, 200, 200)
        dpg.add_text(f"[{time.strftime('%H:%M:%S', time.localtime(m['timestamp']))}] {m['author']}: {m['text']}",
                     parent="chat_list", color=color)

def send_chat(sender, app_data, user_data):
    msg = dpg.get_value("chat_input").strip()
    if not msg or not current_user:
        return
    chat.append({"timestamp": time.time(), "author": current_user["username"], "text": msg})
    save_json(CHAT_FILE, chat)
    dpg.set_value("chat_input", "")
    refresh_chat()

# ---------------- ENGINE ----------------

def import_engine(sender, app_data, user_data):
    global engine
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(title="Importa engine .exe", filetypes=[("Executable", "*.exe")])
    root.destroy()

    if not path:
        return

    engine = {"name": os.path.basename(path), "path": path}
    save_json(ENGINE_FILE, engine)
    add_feed(f"Engine importato: {engine['name']}")
    refresh_engine()

def refresh_engine():
    if not dpg.does_item_exist("engine_info"):
        return

    dpg.delete_item("engine_info", children_only=True)
    dpg.add_text("Engine:", parent="engine_info")

    if not engine:
        dpg.add_text("Nessun engine importato.", parent="engine_info")
        return

    dpg.add_text(f"Nome: {engine['name']}", parent="engine_info")

    if engine.get("path"):
        dpg.add_button(label="Avvia engine", callback=run_exe, user_data=engine["path"], parent="engine_info")

# ---------------- GIOCHI ----------------

def import_game(sender, app_data, user_data):
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(title="Importa gioco .exe", filetypes=[("Executable", "*.exe")])
    root.destroy()

    if not path:
        return

    games.append({
        "name": os.path.basename(path),
        "path": path,
        "multiplayer": False,
        "pseudo_multiplayer": False,
        "servers": [],
        "roles": {
            "player1": "Player 1",
            "player2": "Player 2"
        },
        "inputs_p2": ["W", "A", "S", "D", "Space"],
        "abilities": {
            "player1": ["Attacco", "Schivata"],
            "player2": ["Supporto", "Abilità speciale"]
        },
        "sync_hud": True,
        "streaming_enabled": True,
        "spectator_mode": False,
        "ai_friend_enabled": False
    })
    save_json(GAMES_FILE, games)
    add_feed(f"Gioco importato: {os.path.basename(path)}")
    refresh_games()

def delete_game(sender, app_data, user_data):
    game = user_data
    if game in games:
        games.remove(game)
        save_json(GAMES_FILE, games)
        add_feed(f"Gioco rimosso: {game['name']} (file sul PC NON toccato)")
        refresh_games()

def run_exe(sender, app_data, user_data):
    path = user_data
    if not path or not isinstance(path, str):
        add_feed("Path EXE non valido.")
        return
    if not os.path.isfile(path):
        add_feed("File EXE non trovato.")
        return
    add_feed(f"Avvio: {os.path.basename(path)}")
    try:
        subprocess.Popen([path])
    except Exception as e:
        add_feed(f"Errore avvio EXE: {e}")

def refresh_games():
    if not dpg.does_item_exist("games_list"):
        return

    dpg.delete_item("games_list", children_only=True)

    for g in games:
        with dpg.child_window(width=1200, height=140, parent="games_list"):
            label = g["name"]
            if g.get("multiplayer"):
                label += " [MP]"
            elif g.get("pseudo_multiplayer"):
                label += " [Pseudo-MP]"
            dpg.add_text(label)

            dpg.add_text(f"Ruoli: P1={g['roles']['player1']} / P2={g['roles']['player2']}")
            dpg.add_text(f"Input P2: {', '.join(g['inputs_p2'])}")
            dpg.add_text(f"Abilità P1: {', '.join(g['abilities']['player1'])} | P2: {', '.join(g['abilities']['player2'])}")

            flags = []
            if g["sync_hud"]: flags.append("HUD sync")
            if g["streaming_enabled"]: flags.append("Streaming")
            if g["spectator_mode"]: flags.append("Spettatore")
            if g["ai_friend_enabled"]: flags.append("Amico IA")
            if flags:
                dpg.add_text("Modalità: " + ", ".join(flags))

            with dpg.group(horizontal=True):
                dpg.add_button(label="Avvia", callback=run_exe, user_data=g["path"])
                dpg.add_button(label="HOST MP", callback=host_mp, user_data=g)
                dpg.add_button(label="JOIN MP", callback=join_mp, user_data=g)
                dpg.add_button(label="Editor pseudo-MP", callback=open_pseudo_editor, user_data=g)
                dpg.add_button(label="Rimuovi", callback=delete_game, user_data=g)

# ---------------- MULTIPLAYER / SHARE PLAY ----------------

class P2PConnection(threading.Thread):
    def __init__(self, is_host, ip, port, callback):
        super().__init__(daemon=True)
        self.is_host = is_host
        self.ip = ip
        self.port = port
        self.callback = callback
        self.sock = None
        self.conn = None
        self.running = False

    def run(self):
        self.running = True
        if self.is_host:
            self._host()
        else:
            self._client()

    def _host(self):
        try:
            self.sock = socket.socket()
            self.sock.bind((self.ip, self.port))
            self.sock.listen(1)
            self.callback("In attesa del peer...")
            self.conn, _ = self.sock.accept()
            self.callback("Peer connesso.")
            self._loop()
        except Exception as e:
            self.callback(f"Errore host: {e}")
        finally:
            self._cleanup()

    def _client(self):
        try:
            self.conn = socket.socket()
            self.conn.connect((self.ip, self.port))
            self.callback("Connesso all'HOST.")
            self._loop()
        except Exception as e:
            self.callback(f"Errore client: {e}")
        finally:
            self._cleanup()

    def _loop(self):
        while self.running:
            try:
                data = self.conn.recv(4096)
                if not data:
                    self.callback("Peer disconnesso.")
                    break
                msg = data.decode().strip()
                if msg:
                    self.callback(msg)
            except Exception as e:
                self.callback(f"Errore ricezione: {e}")
                break

    def send(self, text):
        try:
            if self.conn:
                self.conn.sendall((text + "\n").encode())
        except Exception as e:
            self.callback(f"Errore invio: {e}")

    def stop(self):
        self.running = False
        self._cleanup()

    def _cleanup(self):
        try:
            if self.conn:
                self.conn.close()
        except:
            pass
        try:
            if self.sock:
                self.sock.close()
        except:
            pass

def log_share(msg):
    if dpg.does_item_exist("share_log"):
        dpg.add_text(msg, parent="share_log")
        dpg.set_y_scroll("share_log", 1.0)

def host_mp(sender, app_data, user_data):
    global share_conn
    game = user_data
    if not game:
        add_feed("Nessun gioco selezionato.")
        return
    run_exe(None, None, game["path"])
    share_conn = P2PConnection(True, "0.0.0.0", 50001, log_share)
    share_conn.start()
    log_share(f"HOST MP avviato per {game['name']}")

def join_mp(sender, app_data, user_data):
    global share_conn
    game = user_data
    ip = dpg.get_value("mp_join_ip")
    if not ip:
        add_feed("Inserisci IP host.")
        return
    share_conn = P2PConnection(False, ip, 50001, log_share)
    share_conn.start()
    log_share(f"JOIN MP su {game['name']} (host {ip})")

def send_share(sender, app_data, user_data):
    msg = dpg.get_value("share_input").strip()
    if not msg:
        return
    if share_conn:
        share_conn.send(msg)
    log_share(f"[LOCAL] {msg}")
    dpg.set_value("share_input", "")

def stop_share(sender, app_data, user_data):
    global share_conn
    if share_conn:
        share_conn.stop()
        share_conn = None
    log_share("Share Play chiuso.")

# ---------------- PSEUDO-MULTIPLAYER AVANZATO ----------------

def enable_pseudo(sender, app_data, user_data):
    global PSEUDO_MP_GLOBAL_ENABLED
    PSEUDO_MP_GLOBAL_ENABLED = True
    for g in games:
        if not g["multiplayer"]:
            g["pseudo_multiplayer"] = True
    save_json(GAMES_FILE, games)
    add_feed("Pseudo-MP globale abilitato.")
    refresh_games()

def disable_pseudo(sender, app_data, user_data):
    global PSEUDO_MP_GLOBAL_ENABLED
    PSEUDO_MP_GLOBAL_ENABLED = False
    for g in games:
        g["pseudo_multiplayer"] = False
    save_json(GAMES_FILE, games)
    add_feed("Pseudo-MP globale disabilitato.")
    refresh_games()

def open_pseudo_editor(sender, app_data, user_data):
    game = user_data
    if not game:
        return

    if not dpg.does_item_exist("pseudo_editor"):
        with dpg.window(label="Editor pseudo-multiplayer", tag="pseudo_editor", width=600, height=500, pos=(340, 100)):
            dpg.add_text("Configura pseudo-multiplayer per il gioco selezionato")

            dpg.add_input_text(label="Ruolo Player 1", tag="role_p1")
            dpg.add_input_text(label="Ruolo Player 2", tag="role_p2")

            dpg.add_input_text(label="Input P2 (separati da virgola)", tag="inputs_p2_edit")

            dpg.add_input_text(label="Abilità P1 (separate da virgola)", tag="abilities_p1_edit")
            dpg.add_input_text(label="Abilità P2 (separate da virgola)", tag="abilities_p2_edit")

            dpg.add_checkbox(label="Sincronizzazione HUD", tag="sync_hud_edit")
            dpg.add_checkbox(label="Streaming integrato (log)", tag="streaming_edit")
            dpg.add_checkbox(label="Modalità spettatore", tag="spectator_edit")
            dpg.add_checkbox(label="Amico IA", tag="ai_friend_edit")

            dpg.add_button(label="Salva configurazione", callback=save_pseudo_config, user_data=game)
            dpg.add_button(label="Chiudi", callback=lambda s,a,u: dpg.hide_item("pseudo_editor"))
    dpg.show_item("pseudo_editor")

    dpg.set_value("role_p1", game["roles"]["player1"])
    dpg.set_value("role_p2", game["roles"]["player2"])
    dpg.set_value("inputs_p2_edit", ", ".join(game["inputs_p2"]))
    dpg.set_value("abilities_p1_edit", ", ".join(game["abilities"]["player1"]))
    dpg.set_value("abilities_p2_edit", ", ".join(game["abilities"]["player2"]))
    dpg.set_value("sync_hud_edit", game["sync_hud"])
    dpg.set_value("streaming_edit", game["streaming_enabled"])
    dpg.set_value("spectator_edit", game["spectator_mode"])
    dpg.set_value("ai_friend_edit", game["ai_friend_enabled"])

def save_pseudo_config(sender, app_data, user_data):
    game = user_data
    if not game:
        return

    game["roles"]["player1"] = dpg.get_value("role_p1").strip() or "Player 1"
    game["roles"]["player2"] = dpg.get_value("role_p2").strip() or "Player 2"

    inputs_raw = dpg.get_value("inputs_p2_edit")
    game["inputs_p2"] = [x.strip() for x in inputs_raw.split(",") if x.strip()]

    abil_p1_raw = dpg.get_value("abilities_p1_edit")
    abil_p2_raw = dpg.get_value("abilities_p2_edit")
    game["abilities"]["player1"] = [x.strip() for x in abil_p1_raw.split(",") if x.strip()]
    game["abilities"]["player2"] = [x.strip() for x in abil_p2_raw.split(",") if x.strip()]

    game["sync_hud"] = bool(dpg.get_value("sync_hud_edit"))
    game["streaming_enabled"] = bool(dpg.get_value("streaming_edit"))
    game["spectator_mode"] = bool(dpg.get_value("spectator_edit"))
    game["ai_friend_enabled"] = bool(dpg.get_value("ai_friend_edit"))

    save_json(GAMES_FILE, games)
    add_feed(f"Pseudo-MP aggiornato per {game['name']}. Ruoli: {game['roles']['player1']}/{game['roles']['player2']}")
    refresh_games()

# ---------------- AMICO IA ----------------

def ia_friend_loop(game):
    global ia_running
    ia_running = True
    add_feed(f"Amico IA attivo per {game['name']} (ruolo {game['roles']['player2']})")
    while ia_running:
        time.sleep(random.uniform(1.0, 3.0))
        if not game["ai_friend_enabled"]:
            break
        if game["spectator_mode"]:
            continue
        if game["inputs_p2"]:
            action = random.choice(game["inputs_p2"])
            add_feed(f"[IA {game['roles']['player2']}] usa input: {action}")
    add_feed("Amico IA terminato.")

def start_ia_friend(game):
    global ia_thread, ia_running
    if ia_thread and ia_thread.is_alive():
        return
    ia_thread = threading.Thread(target=ia_friend_loop, args=(game,), daemon=True)
    ia_thread.start()

def stop_ia_friend():
    global ia_running
    ia_running = False

# ---------------- TEMI / CONFIG ----------------

def apply_theme():
    if CURRENT_THEME == "dark":
        bg = (15, 15, 18)
        tx = (230, 230, 230)
    elif CURRENT_THEME == "light":
        bg = (245, 245, 245)
        tx = (20, 20, 20)
    else:
        bg = (20, 20, 30)
        tx = (0, 255, 255)

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, bg)
            dpg.add_theme_color(dpg.mvThemeCol_Text, tx)
    dpg.bind_theme(t)

def change_theme(sender, app_data, user_data):
    global CURRENT_THEME
    CURRENT_THEME = app_data
    settings["theme"] = CURRENT_THEME
    save_json(SETTINGS_FILE, settings)
    apply_theme()

def change_language(sender, app_data, user_data):
    global CURRENT_LANGUAGE
    CURRENT_LANGUAGE = app_data
    settings["language"] = CURRENT_LANGUAGE
    save_json(SETTINGS_FILE, settings)
    add_feed(f"Lingua: {CURRENT_LANGUAGE}")

def change_controller(sender, app_data, user_data):
    global CURRENT_CONTROLLER
    CURRENT_CONTROLLER = app_data
    settings["controller"] = CURRENT_CONTROLLER
    save_json(SETTINGS_FILE, settings)
    add_feed(f"Controller: {CURRENT_CONTROLLER}")

def change_performance(sender, app_data, user_data):
    global CURRENT_PERFORMANCE
    CURRENT_PERFORMANCE = app_data
    settings["performance"] = CURRENT_PERFORMANCE
    save_json(SETTINGS_FILE, settings)
    add_feed(f"Prestazioni: {CURRENT_PERFORMANCE}")

# ---------------- AMICI ----------------

def send_friend_request(sender, app_data, user_data):
    if not current_user:
        add_feed("Devi essere loggato.")
        return
    target_name = dpg.get_value("friend_add_input").strip()
    if not target_name:
        return
    target = find_user(target_name)
    if not target:
        add_feed("Utente inesistente.")
        return
    if current_user["username"] in target.get("blocked_users", []):
        add_feed("Sei bloccato da questo utente.")
        return
    if current_user["username"] in target.get("friend_requests", []):
        add_feed("Richiesta già inviata.")
        return
    if current_user["username"] in target.get("friends", []):
        add_feed("Siete già amici.")
        return
    target.setdefault("friend_requests", []).append(current_user["username"])
    save_json(USERS_FILE, users)
    add_feed(f"Richiesta inviata a {target_name}")
    refresh_friends()

def accept_friend_request(from_name):
    if not current_user:
        return
    if from_name not in current_user.get("friend_requests", []):
        return
    current_user["friend_requests"].remove(from_name)
    current_user.setdefault("friends", []).append(from_name)
    other = find_user(from_name)
    if other:
        other.setdefault("friends", []).append(current_user["username"])
    save_json(USERS_FILE, users)
    add_feed(f"Hai accettato {from_name}.")
    refresh_friends()

def reject_friend_request(from_name):
    if not current_user:
        return
    if from_name in current_user.get("friend_requests", []):
        current_user["friend_requests"].remove(from_name)
        save_json(USERS_FILE, users)
        add_feed(f"Hai rifiutato {from_name}.")
        refresh_friends()

def block_user(sender, app_data, user_data):
    if not current_user:
        return
    name = dpg.get_value("block_input").strip()
    if not name:
        return
    if name not in current_user.get("blocked_users", []):
        current_user.setdefault("blocked_users", []).append(name)
        save_json(USERS_FILE, users)
        add_feed(f"Hai bloccato {name}.")
        refresh_friends()

def unblock_user(sender, app_data, user_data):
    if not current_user:
        return
    name = dpg.get_value("unblock_input").strip()
    if not name:
        return
    if name in current_user.get("blocked_users", []):
        current_user["blocked_users"].remove(name)
        save_json(USERS_FILE, users)
        add_feed(f"Hai sbloccato {name}.")
        refresh_friends()

def refresh_friends():
    if not dpg.does_item_exist("friends_list"):
        return
    dpg.delete_item("friends_list", children_only=True)
    if not current_user:
        dpg.add_text("Nessun utente loggato.", parent="friends_list")
        return
    dpg.add_text(f"Utente: {current_user['username']}", parent="friends_list")
    dpg.add_text("Amici:", parent="friends_list")
    for f in current_user.get("friends", []):
        dpg.add_text(f"• {f}", parent="friends_list")

    if dpg.does_item_exist("friend_requests_list"):
        dpg.delete_item("friend_requests_list", children_only=True)
        dpg.add_text("Richieste in arrivo:", parent="friend_requests_list")
        for r in current_user.get("friend_requests", []):
            with dpg.group(parent="friend_requests_list", horizontal=True):
                dpg.add_text(f"Richiesta da: {r}")
                dpg.add_button(label="Accetta", callback=lambda s,a,u=r: accept_friend_request(u))
                dpg.add_button(label="Rifiuta", callback=lambda s,a,u=r: reject_friend_request(u))

# ---------------- UI ----------------

def show_page(page_tag):
    for p in ["page_home", "page_games", "page_chat", "page_friends", "page_share", "page_engine", "page_settings"]:
        dpg.configure_item(p, show=(p == page_tag))

def build_ui():
    # LOGIN
    with dpg.window(label="Login", width=420, height=320, pos=(430, 220), tag="login_window"):
        dpg.add_text("Login Skylox")
        dpg.add_input_text(label="Username", tag="login_username")
        dpg.add_input_text(label="Password", tag="login_password", password=True)
        dpg.add_text("Forza password:", tag="pw_strength_label")
        dpg.add_button(label="Controlla forza", callback=update_pw_strength)
        dpg.add_button(label="Login / Registrazione", callback=on_login)
        dpg.add_child_window(width=400, height=120, tag="accounts_list")
        refresh_account_list()

    # MAIN
    with dpg.window(label="Skylox Console", tag="console_ui_root", width=1280, height=720, show=False):

        with dpg.group(horizontal=True):
            dpg.add_text("SKYLOX", color=(0, 255, 255))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Home", callback=lambda s,a,u: show_page("page_home"))
            dpg.add_button(label="Giochi", callback=lambda s,a,u: show_page("page_games"))
            dpg.add_button(label="Chat", callback=lambda s,a,u: show_page("page_chat"))
            dpg.add_button(label="Amici", callback=lambda s,a,u: show_page("page_friends"))
            dpg.add_button(label="Share Play", callback=lambda s,a,u: show_page("page_share"))
            dpg.add_button(label="Engine", callback=lambda s,a,u: show_page("page_engine"))
            dpg.add_button(label="Impostazioni", callback=lambda s,a,u: show_page("page_settings"))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Importa gioco (.exe)", callback=import_game)
            dpg.add_button(label="Importa engine (.exe)", callback=import_engine)
            dpg.add_spacer(width=20)
            dpg.add_button(label="Disconnetti", callback=logout)
            dpg.add_button(label="Esci (rimuovi account)", callback=exit_account)
            dpg.add_button(label="Cambia account", callback=switch_account)

        with dpg.child_window(width=1260, height=660):

            # HOME
            with dpg.group(tag="page_home", show=True):
                dpg.add_text("Home / Feed")
                dpg.add_child_window(width=1240, height=600, tag="feed_list")
                add_feed("Skylox avviato.")

            # GIOCHI
            with dpg.group(tag="page_games", show=False):
                dpg.add_text("Giochi")
                dpg.add_child_window(width=1240, height=600, tag="games_list")
                refresh_games()

            # CHAT
            with dpg.group(tag="page_chat", show=False):
                dpg.add_text("Chat")
                dpg.add_child_window(width=1240, height=520, tag="chat_list")
                dpg.add_input_text(label="Messaggio", tag="chat_input", width=600)
                dpg.add_button(label="Invia", callback=send_chat)

            # AMICI
            with dpg.group(tag="page_friends", show=False):
                dpg.add_text("Amici")
                dpg.add_child_window(width=1240, height=200, tag="friends_list")
                dpg.add_child_window(width=1240, height=200, tag="friend_requests_list")
                dpg.add_input_text(label="Aggiungi amico (username)", tag="friend_add_input", width=400)
                dpg.add_button(label="Invia richiesta", callback=send_friend_request)
                dpg.add_input_text(label="Blocca utente", tag="block_input", width=400)
                dpg.add_button(label="Blocca", callback=block_user)
                dpg.add_input_text(label="Sblocca utente", tag="unblock_input", width=400)
                dpg.add_button(label="Sblocca", callback=unblock_user)

            # SHARE PLAY
            with dpg.group(tag="page_share", show=False):
                dpg.add_text("Share Play / Multiplayer")
                dpg.add_input_text(label="IP Host", tag="mp_join_ip", width=400)
                dpg.add_button(label="STOP", callback=stop_share)
                dpg.add_input_text(label="Messaggio", tag="share_input", width=400)
                dpg.add_button(label="Invia", callback=send_share)
                dpg.add_child_window(width=1240, height=300, tag="share_log")

            # ENGINE
            with dpg.group(tag="page_engine", show=False):
                dpg.add_text("Engine")
                dpg.add_child_window(width=1240, height=200, tag="engine_info")
                refresh_engine()

            # IMPOSTAZIONI
            with dpg.group(tag="page_settings", show=False):
                dpg.add_text("Impostazioni")
                dpg.add_combo(label="Tema", items=THEMES, default_value=CURRENT_THEME, callback=change_theme)
                dpg.add_combo(label="Lingua", items=LANGUAGES, default_value=CURRENT_LANGUAGE, callback=change_language)
                dpg.add_combo(label="Controller", items=CONTROLLER_MODES, default_value=CURRENT_CONTROLLER, callback=change_controller)
                dpg.add_combo(label="Prestazioni", items=PERFORMANCE_MODES, default_value=CURRENT_PERFORMANCE, callback=change_performance)
                dpg.add_button(label="Abilita pseudo-multiplayer globale", callback=enable_pseudo)
                dpg.add_button(label="Disabilita pseudo-multiplayer globale", callback=disable_pseudo)

# ---------------- REFRESH ALL ----------------

def refresh_all_ui():
    refresh_account_list()
    refresh_games()
    refresh_chat()
    refresh_friends()
    refresh_engine()

# ---------------- LOAD / MAIN ----------------

def load_all():
    global users, games, chat, feed, settings, accounts, engine
    global CURRENT_THEME, CURRENT_LANGUAGE, CURRENT_CONTROLLER, CURRENT_PERFORMANCE

    users    = load_json(USERS_FILE, [])
    games    = load_json(GAMES_FILE, [])
    chat     = load_json(CHAT_FILE, [])
    feed     = load_json(FEED_FILE, [])
    settings = load_json(SETTINGS_FILE, {
        "theme": "system",
        "language": "Italiano",
        "controller": "Keyboard/Mouse",
        "performance": "Medium"
    })
    accounts = load_json(ACCOUNTS_FILE, [])
    engine   = load_json(ENGINE_FILE, None)

    CURRENT_THEME       = settings.get("theme", "system")
    CURRENT_LANGUAGE    = settings.get("language", "Italiano")
    CURRENT_CONTROLLER  = settings.get("controller", "Keyboard/Mouse")
    CURRENT_PERFORMANCE = settings.get("performance", "Medium")

def main():
    ensure_data()
    load_all()

    dpg.create_context()
    dpg.create_viewport(title="Skylox Alpha", width=1280, height=720)

    build_ui()
    apply_theme()

    dpg.setup_dearpygui()
    dpg.show_viewport()

    auto_login()

    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    main()

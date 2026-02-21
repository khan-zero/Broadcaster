import os
import sys
import json
import time
import threading
import asyncio
import random
import re
import tkinter as tk
import tkinter.messagebox
import webbrowser
import logging
import traceback
from datetime import datetime
from typing import List, Dict, Optional, Union

import customtkinter as ctk
import requests
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors
from telethon.tl.types import Dialog, InputPeerChannel, InputPeerChat, InputPeerUser, ChannelFull, ChatFull
from telethon.tl.functions.channels import GetFullChannelRequest

# --- Logging Setup ---
ERROR_LOG_FILE = "error_log.txt"
logging.basicConfig(
    filename=ERROR_LOG_FILE,
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# --- Load Environment ---
if hasattr(sys, '_MEIPASS'):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

env_path = os.path.join(base_path, '.env')
load_dotenv(env_path)

# --- Configuration (CLEAN VERSION) ---
SESSIONS_DIR = "sessions"
GROUPS_FILE = "groups.json"
DRAFTS_FILE = "drafts.json"
BLACKLIST_FILE = "blacklist.json"
SETTINGS_FILE = "settings.json"

# API Keys with safe conversion
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")

try:
    if API_ID:
        API_ID = int(API_ID)
except ValueError:
    logging.error(f"Invalid TG_API_ID found: {API_ID}")
    API_ID = None

# Ensure sessions directory exists
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

# ── Windows 11 Design Tokens ──────────────────────────────────────────────────
WIN11 = {
    # Backgrounds
    "bg_base":        "#1C1C1C",   # App canvas
    "bg_surface":     "#242424",   # Cards / panels
    "bg_overlay":     "#2C2C2C",   # Raised cards
    "bg_input":       "#323232",   # Entry fields
    "bg_hover":       "#3A3A3A",   # Hover state

    # Accent (Win11 default blue)
    "accent":         "#0078D4",
    "accent_hover":   "#1383D8",
    "accent_dim":     "#005A9E",

    # Status
    "success":        "#107C10",
    "success_hover":  "#0D6A0D",
    "warning":        "#FF8C00",
    "danger":         "#C42B1C",
    "danger_hover":   "#A3261A",

    # Text
    "text_primary":   "#FFFFFF",
    "text_secondary": "#ABABAB",
    "text_disabled":  "#686868",

    # Borders
    "border":         "#3D3D3D",
    "border_focus":   "#0078D4",

    # Sidebar
    "sidebar_bg":     "#202020",
    "sidebar_active": "#2C2C2C",
}

FONT_FAMILY = "Segoe UI"

# ── Theme Setup ───────────────────────────────────────────────────────────────
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_spintax(text: str) -> str:
    """Parses spintax like {Hello|Hi|Hey} and picks a random value."""
    while True:
        match = re.search(r'\{([^{}]*)\}', text)
        if not match:
            break
        options = match.group(1).split('|')
        text = text[:match.start()] + random.choice(options) + text[match.end():]
    return text


# ── Async infrastructure ──────────────────────────────────────────────────────
class AsyncLoopThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coroutine(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


# ── Telegram backend ──────────────────────────────────────────────────────────
class TelegramManager:
    def __init__(self, loop_thread: AsyncLoopThread, log_callback):
        self.loop_thread = loop_thread
        self.log = log_callback
        self.client = None
        self.phone = None
        self.is_connected = False

    def connect(self, phone=None):
        if phone:
            self.phone = phone
            session_path = os.path.join(SESSIONS_DIR, f"{phone}")
            if not os.path.exists(SESSIONS_DIR):
                os.makedirs(SESSIONS_DIR)
            self.client = TelegramClient(session_path, API_ID, API_HASH, loop=self.loop_thread.loop)

        if not self.client:
            session_path = os.path.join(SESSIONS_DIR, "default")
            if not os.path.exists(SESSIONS_DIR):
                os.makedirs(SESSIONS_DIR)
            self.client = TelegramClient(session_path, API_ID, API_HASH, loop=self.loop_thread.loop)

        future = self.loop_thread.run_coroutine(self.client.connect())
        return future

    def is_user_authorized(self):
        future = self.loop_thread.run_coroutine(self.client.is_user_authorized())
        return future

    def send_code_request(self, phone):
        self.phone = phone
        return self.loop_thread.run_coroutine(self.client.send_code_request(phone))

    def sign_in(self, code, password=None):
        return self.loop_thread.run_coroutine(self._sign_in_wrapper(code, password))

    async def _sign_in_wrapper(self, code, password):
        try:
            await self.client.sign_in(self.phone, code)
        except errors.SessionPasswordNeededError:
            if password:
                await self.client.sign_in(password=password)
            else:
                raise

    def get_dialogs(self):
        return self.loop_thread.run_coroutine(self._get_groups())

    async def _get_groups(self):
        groups = []
        blacklist = []
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    blacklist = json.load(f)
            except Exception:
                pass

        async for dialog in self.client.iter_dialogs():
            is_group = dialog.is_group
            is_megagroup = False
            if dialog.is_channel:
                entity = dialog.entity
                if getattr(entity, 'megagroup', False):
                    is_megagroup = True

            if not (is_group or is_megagroup):
                continue

            entity = dialog.entity
            can_send = True
            if hasattr(entity, 'restricted') and entity.restricted:
                can_send = False
            if hasattr(entity, 'left') and entity.left:
                can_send = False

            if not can_send:
                continue

            slowmode = getattr(entity, 'slowmode_seconds', 0) or 0

            groups.append({
                "id": dialog.id,
                "title": dialog.name,
                "type": "megagroup" if is_megagroup else "group",
                "slowmode": slowmode,
                "slowmode_until": 0,
                "is_blacklisted": dialog.id in blacklist
            })
        return groups

    def send_message(self, entity_id, message):
        return self.loop_thread.run_coroutine(self.client.send_message(entity_id, message))


# ── Reusable Win11 widget helpers ─────────────────────────────────────────────
def make_card(parent, **kw) -> ctk.CTkFrame:
    """A rounded 'card' that mimics Win11 surface elevation."""
    defaults = dict(
        corner_radius=10,
        fg_color=WIN11["bg_surface"],
        border_width=1,
        border_color=WIN11["border"],
    )
    defaults.update(kw)
    return ctk.CTkFrame(parent, **defaults)


def make_section_label(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=(FONT_FAMILY, 11),
        text_color=WIN11["text_secondary"],
    )


def make_heading(parent, text: str, size: int = 14) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=(FONT_FAMILY, size, "bold"),
        text_color=WIN11["text_primary"],
    )


def make_button(parent, text: str, command=None, style="accent", width=120, height=34, **kw) -> ctk.CTkButton:
    """Win11-style button with accent / neutral / danger variants."""
    styles = {
        "accent":  dict(fg_color=WIN11["accent"],  hover_color=WIN11["accent_hover"],  text_color=WIN11["text_primary"]),
        "neutral": dict(fg_color=WIN11["bg_input"], hover_color=WIN11["bg_hover"],     text_color=WIN11["text_primary"],
                        border_width=1, border_color=WIN11["border"]),
        "danger":  dict(fg_color=WIN11["danger"],   hover_color=WIN11["danger_hover"],  text_color=WIN11["text_primary"]),
        "success": dict(fg_color=WIN11["success"],  hover_color=WIN11["success_hover"], text_color=WIN11["text_primary"]),
        "ghost":   dict(fg_color="transparent",     hover_color=WIN11["bg_hover"],      text_color=WIN11["text_primary"],
                        border_width=1, border_color=WIN11["border"]),
    }
    cfg = styles.get(style, styles["accent"])
    cfg.update(kw)
    return ctk.CTkButton(
        parent, text=text, command=command,
        width=width, height=height,
        corner_radius=6,
        font=(FONT_FAMILY, 12),
        **cfg,
    )


def make_entry(parent, placeholder: str = "", width: int = 240, show: str = "") -> ctk.CTkEntry:
    return ctk.CTkEntry(
        parent,
        placeholder_text=placeholder,
        width=width,
        height=36,
        corner_radius=6,
        fg_color=WIN11["bg_input"],
        border_color=WIN11["border"],
        border_width=1,
        text_color=WIN11["text_primary"],
        placeholder_text_color=WIN11["text_disabled"],
        font=(FONT_FAMILY, 12),
        show=show,
    )


# ── Custom Widgets ────────────────────────────────────────────────────────────
class ModernAlert(ctk.CTkToplevel):
    def __init__(self, parent, title, message, style="info", callback=None):
        super().__init__(parent)
        self.title("")
        self.geometry("420x220")
        self.resizable(False, False)
        self.configure(fg_color=WIN11["bg_surface"])
        self.attributes('-topmost', True)
        self.after(10, self._center_window)
        
        self.callback = callback
        
        # Icon mapping
        icons = {"info": ("ℹ", WIN11["accent"]), "warning": ("⚠", WIN11["warning"]), "error": ("❌", WIN11["danger"]), "question": ("❓", WIN11["accent"])}
        icon_char, icon_color = icons.get(style, icons["info"])
        
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=24, pady=24)
        
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(header, text=icon_char, font=(FONT_FAMILY, 32), text_color=icon_color).pack(side="left")
        make_heading(header, title, 16).pack(side="left", padx=12)
        
        ctk.CTkLabel(main_frame, text=message, font=(FONT_FAMILY, 12), text_color=WIN11["text_secondary"], 
                     wraplength=360, justify="left").pack(fill="x", pady=(0, 20))
        
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", side="bottom")
        
        if style == "question":
            make_button(btn_frame, "Yes", command=lambda: self._close(True), style="accent", width=100).pack(side="right")
            make_button(btn_frame, "No", command=lambda: self._close(False), style="neutral", width=100).pack(side="right", padx=10)
        else:
            make_button(btn_frame, "OK", command=lambda: self._close(True), style="accent", width=100).pack(side="right")

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'+{x}+{y}')

    def _close(self, result):
        self.destroy()
        if self.callback:
            self.callback(result)

class LoadingWindow(ctk.CTkToplevel):
    def __init__(self, parent, message="Connecting to Telegram..."):
        super().__init__(parent)
        self.overrideredirect(True)
        self.geometry("380x180")
        self.configure(fg_color=WIN11["bg_surface"])
        self.attributes('-topmost', True)
        self._center_window()
        
        # Border
        border = ctk.CTkFrame(self, fg_color=WIN11["border"], corner_radius=12)
        border.pack(fill="both", expand=True, padx=1, pady=1)
        inner = ctk.CTkFrame(border, fg_color=WIN11["bg_surface"], corner_radius=11)
        inner.pack(fill="both", expand=True, padx=0, pady=0)

        # Content
        self.logo_label = ctk.CTkLabel(inner, text="✈", font=(FONT_FAMILY, 40), text_color=WIN11["accent"])
        self.logo_label.pack(pady=(25, 5))
        
        self.msg_label = ctk.CTkLabel(inner, text=message, font=(FONT_FAMILY, 13), text_color=WIN11["text_primary"])
        self.msg_label.pack(pady=5)
        
        self.progress = ctk.CTkProgressBar(inner, width=280, height=4, indeterminate_speed=1.5,
                                           fg_color=WIN11["bg_input"], progress_color=WIN11["accent"])
        self.progress.pack(pady=(15, 0))
        self.progress.start()
        
        # Setup real logo if available
        self.after(100, self._load_logo)

    def _load_logo(self):
        try:
            from PIL import Image
            if os.path.exists("app_logo_image.png"):
                img = ctk.CTkImage(light_image=Image.open("app_logo_image.png"),
                                  dark_image=Image.open("app_logo_image.png"),
                                  size=(60, 60))
                self.logo_label.configure(image=img, text="")
        except Exception:
            pass

    def _center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (190)
        y = (self.winfo_screenheight() // 2) - (90)
        self.geometry(f'380x180+{x}+{y}')

# ── Main Application ──────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Telegram Broadcaster Pro")
        self.geometry("1160x720")
        self.minsize(900, 600)
        self.configure(fg_color=WIN11["bg_base"])
        
        # Set App Icon
        self._set_app_icon()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Backend (Fixing logging accessibility)
        self.loop_thread = AsyncLoopThread()
        self.loop_thread.start()
        self.manager = TelegramManager(self.loop_thread, self._safe_log)

        # State
        self.groups = []
        self.selected_groups = set()
        self.drafts = self.load_drafts()
        self.is_broadcasting = False
        self.group_last_sent = {}
        self.settings = self.load_settings()
        self.pending_blacklist = self.load_blacklist_local()
        self.group_vars = {}
        self.slowmode_labels = {}
        self.bl_buttons = {}
        self.current_edit_index = None
        self._active_nav = None

        if not API_ID or not API_HASH:
            self.after(500, lambda: self.show_error(
                "Missing Credentials",
                "Error: API Keys not found. Please contact the administrator."
            ))
            return

        # Start with a loading window
        self.withdraw()
        self.loading = LoadingWindow(self)
        self.check_initial_login()

    def _set_app_icon(self):
        try:
            if os.path.exists("app_logo_image.png"):
                from PIL import Image, ImageTk
                img = Image.open("app_logo_image.png")
                # Resize to a standard icon size to avoid X11 BadLength errors on Linux
                img = img.resize((64, 64), Image.LANCZOS)
                self.iconphoto(False, ImageTk.PhotoImage(img))
        except Exception as e:
            print(f"Failed to set icon: {e}")

    def _safe_log(self, message):
        # Thread-safe logging bridge
        def _exec():
            if self.winfo_exists():
                self.log_message(message)
        self.after(0, _exec)

    # ── Custom Messageboxes ───────────────────────────────────────────────────
    def show_error(self, title, message):
        ModernAlert(self, title, message, style="error")

    def show_info(self, title, message):
        ModernAlert(self, title, message, style="info")

    def ask_yes_no(self, title, message, callback):
        ModernAlert(self, title, message, style="question", callback=callback)

    # ── Exception handler ─────────────────────────────────────────────────────
    def handle_exception(self, exc_type, exc_value, exc_traceback):
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logging.error(f"Unhandled Exception: {err_msg}")
        self.show_error("Unexpected Error", "Details are saved to error_log.txt")

    # ── Logger ────────────────────────────────────────────────────────────────
    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}]  {message}\n"
        print(full_msg.strip())

        if hasattr(self, 'log_box'):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", full_msg)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        if "error" in message.lower() or "failed" in message.lower():
            logging.error(message)

    # ── Groups helpers ────────────────────────────────────────────────────────
    def refresh_groups(self):
        self.log_message("Fetching groups…")
        future = self.manager.get_dialogs()
        self.after(100, self._wait_for_groups, future)

    def _wait_for_groups(self, future):
        try:
            if future.done():
                groups = future.result()
                self.groups = groups
                self.save_groups_local(groups)
                self.populate_groups_list(groups)
                self.log_message(f"Fetched {len(groups)} groups.")
            else:
                self.after(100, self._wait_for_groups, future)
        except Exception as e:
            self.log_message(f"Error fetching groups: {e}")

    def populate_groups_list(self, groups):
        if hasattr(self, 'groups_scroll'):
            for widget in self.groups_scroll.winfo_children():
                widget.destroy()

        self.group_vars.clear()
        self.slowmode_labels.clear()
        self.bl_buttons.clear()

        sorted_groups = sorted(groups, key=lambda g: g.get('slowmode_until', 0))

        for grp in sorted_groups:
            gid = grp['id']
            is_blacklisted = gid in self.pending_blacklist

            row = ctk.CTkFrame(self.groups_scroll, fg_color=WIN11["bg_surface"],
                               corner_radius=6, border_width=1, border_color=WIN11["border"])
            row.pack(fill="x", pady=3, padx=2)

            var = ctk.BooleanVar()
            label_text = grp['title']

            chk = ctk.CTkCheckBox(
                row, text=label_text, variable=var,
                font=(FONT_FAMILY, 12),
                text_color=WIN11["text_disabled"] if is_blacklisted else WIN11["text_primary"],
                fg_color=WIN11["accent"],
                hover_color=WIN11["accent_hover"],
                border_color=WIN11["border"],
                corner_radius=4,
                checkmark_color=WIN11["text_primary"],
            )
            chk.pack(side="left", padx=10, pady=8)

            if is_blacklisted:
                chk.configure(state="disabled")
            else:
                self.group_vars[gid] = var

            # Slowmode badge
            if grp.get('slowmode') or grp.get('slowmode_until'):
                wait = grp.get('slowmode_until', 0)
                badge_txt = f"⏱ {wait}s" if wait > 0 else f"⏱ {grp['slowmode']}s"
                sm_lbl = ctk.CTkLabel(row, text=badge_txt,
                                      font=(FONT_FAMILY, 10),
                                      text_color=WIN11["warning"],
                                      fg_color=WIN11["bg_overlay"],
                                      corner_radius=4, padx=6, pady=2)
                sm_lbl.pack(side="right", padx=(4, 6))
                self.slowmode_labels[gid] = sm_lbl

            # Blacklist toggle
            bl_text  = "✓ Listed" if is_blacklisted else "Block"
            bl_style = "danger" if is_blacklisted else "neutral"
            bl_btn = make_button(row, bl_text, width=62, height=26,
                                 style=bl_style,
                                 command=lambda g=grp: self.toggle_blacklist_ui(g))
            bl_btn.pack(side="right", padx=4)
            self.bl_buttons[gid] = bl_btn

    def update_slowmode_countdowns(self):
        for gid, grp in [(g['id'], g) for g in self.groups if g['id'] in self.slowmode_labels]:
            if grp.get('slowmode_until', 0) > 0:
                grp['slowmode_until'] -= 1
                wait = grp['slowmode_until']
                self.slowmode_labels[gid].configure(
                    text=f"⏱ {wait}s" if wait > 0 else f"⏱ {grp['slowmode']}s"
                )
            elif grp.get('slowmode', 0) > 0:
                self.slowmode_labels[gid].configure(text=f"⏱ {grp['slowmode']}s")

        self.after(1000, self.update_slowmode_countdowns)

    def toggle_all_groups(self):
        val = self.select_all_var.get()
        for var in self.group_vars.values():
            var.set(val)

    def toggle_blacklist_ui(self, group):
        gid = group['id']
        if gid in self.pending_blacklist:
            self.pending_blacklist.remove(gid)
            self.bl_buttons[gid].configure(
                text="Block",
                fg_color=WIN11["bg_input"],
                hover_color=WIN11["bg_hover"],
            )
        else:
            self.pending_blacklist.add(gid)
            self.bl_buttons[gid].configure(
                text="✓ Listed",
                fg_color=WIN11["danger"],
                hover_color=WIN11["danger_hover"],
            )
        self.apply_bl_btn.configure(fg_color=WIN11["success"], hover_color=WIN11["success_hover"])

    def apply_blacklist(self):
        try:
            with open(BLACKLIST_FILE, "w") as f:
                json.dump(list(self.pending_blacklist), f)
            self.log_message("Blacklist updated and saved.")
            self.apply_bl_btn.configure(fg_color=WIN11["bg_input"], hover_color=WIN11["bg_hover"])
            self.refresh_groups()
        except Exception as e:
            self.log_message(f"Failed to save blacklist: {e}")

    # ── Auth helpers ──────────────────────────────────────────────────────────
    def check_initial_login(self):
        phone = self.settings.get("last_phone")
        future = self.manager.connect(phone)
        self.after(1000, self._check_auth_after_connect, future)

    def _check_auth_after_connect(self, connect_future):
        if not connect_future.done():
            self.after(500, self._check_auth_after_connect, connect_future)
            return
        try:
            connect_future.result()
            auth_future = self.manager.is_user_authorized()
            self.after(500, self._process_auth_result, auth_future)
        except Exception as e:
            self.log_message(f"Connection error: {e}")

    def _process_auth_result(self, auth_future):
        if not auth_future.done():
            self.after(500, self._process_auth_result, auth_future)
            return
        
        # Close loading window
        if hasattr(self, 'loading') and self.loading:
            self.loading.destroy()
            self.loading = None
        self.deiconify()

        try:
            if auth_future.result():
                self.show_main_ui()
                self.log_message("Logged in automatically.")
                self.refresh_groups()
            else:
                self.create_login_ui()
                self.log_message("Please log in.")
        except Exception as e:
            self.create_login_ui()
            self.log_message(f"Auth check failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # LOGIN SCREEN  (Win11-style centered card)
    # ─────────────────────────────────────────────────────────────────────────
    def create_login_ui(self):
        # Blurred backdrop strip
        self.login_bg = ctk.CTkFrame(self, fg_color=WIN11["bg_base"])
        self.login_bg.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Central card
        card = ctk.CTkFrame(
            self, width=380, corner_radius=12,
            fg_color=WIN11["bg_surface"],
            border_width=1, border_color=WIN11["border"],
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.grid_propagate(False)
        self.login_frame = card

        # App icon placeholder + title
        self.login_icon_lbl = ctk.CTkLabel(card, text="✈", font=(FONT_FAMILY, 40),
                                text_color=WIN11["accent"])
        self.login_icon_lbl.pack(pady=(32, 0))
        
        # Load real logo for login
        self._load_image_to_label(self.login_icon_lbl, (80, 80))

        make_heading(card, "Telegram Broadcaster Pro", 18).pack(pady=(6, 2))
        make_section_label(card, "Sign in to your Telegram account").pack(pady=(0, 24))

        # Divider
        ctk.CTkFrame(card, height=1, fg_color=WIN11["border"]).pack(fill="x", padx=24)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=28, pady=20)

        make_section_label(inner, "PHONE NUMBER").pack(anchor="w", pady=(0, 4))
        self.phone_entry = make_entry(inner, "+1 234 567 8900", width=320)
        self.phone_entry.pack(fill="x")

        self.send_code_btn = make_button(
            inner, "Send Verification Code",
            command=self.on_send_code, style="accent", width=320, height=38
        )
        self.send_code_btn.pack(pady=(14, 0))

        # These appear after code is sent
        self.code_entry     = make_entry(inner, "Verification code", width=320)
        self.password_entry = make_entry(inner, "2FA password (if required)", width=320, show="•")
        self.login_btn      = make_button(inner, "Sign In", command=self.on_login,
                                          style="success", width=320, height=38)

        self.login_log_lbl = ctk.CTkLabel(
            card, text="", font=(FONT_FAMILY, 11),
            text_color=WIN11["text_secondary"]
        )
        self.login_log_lbl.pack(pady=(0, 24))

    def on_send_code(self):
        phone = self.phone_entry.get().strip()
        if not phone:
            self.login_log_lbl.configure(text="Please enter a phone number.", text_color=WIN11["warning"])
            return
        self.login_log_lbl.configure(text="Connecting…", text_color=WIN11["text_secondary"])
        self.settings["last_phone"] = phone
        self.save_settings()
        future = self.manager.connect(phone)
        self.after(100, self._wait_for_connect_before_code, future, phone)

    def _wait_for_connect_before_code(self, future, phone):
        try:
            if future.done():
                future.result()
                self.login_log_lbl.configure(text="Sending code…", text_color=WIN11["text_secondary"])
                code_future = self.manager.send_code_request(phone)
                self.after(100, self._wait_for_code_req, code_future)
            else:
                self.after(100, self._wait_for_connect_before_code, future, phone)
        except Exception as e:
            self.login_log_lbl.configure(text=f"Connection Error: {e}", text_color=WIN11["danger"])

    def _wait_for_code_req(self, future):
        try:
            if future.done():
                future.result()
                self.login_log_lbl.configure(
                    text="✓  Code sent — check Telegram", text_color=WIN11["success"])
                self.code_entry.pack(fill="x", pady=(10, 0))
                self.password_entry.pack(fill="x", pady=(10, 0))
                self.login_btn.pack(fill="x", pady=(14, 0))
                self.send_code_btn.configure(state="disabled", text="Code Sent ✓")
            else:
                self.after(100, self._wait_for_code_req, future)
        except Exception as e:
            self.login_log_lbl.configure(text=f"Error: {e}", text_color=WIN11["danger"])

    def on_login(self):
        code = self.code_entry.get()
        password = self.password_entry.get()
        if not code:
            self.login_log_lbl.configure(text="Please enter the code.", text_color=WIN11["warning"])
            return
        self.login_log_lbl.configure(text="Signing in…", text_color=WIN11["text_secondary"])
        future = self.manager.sign_in(code, password if password else None)
        self.after(100, self._wait_for_login, future)

    def _wait_for_login(self, future):
        try:
            if future.done():
                future.result()
                self.login_log_lbl.configure(text="✓  Logged in!", text_color=WIN11["success"])
                
                def _proceed():
                    if hasattr(self, 'login_frame') and self.login_frame:
                        self.login_frame.destroy()
                    if hasattr(self, 'login_bg') and self.login_bg:
                        self.login_bg.destroy()
                    self.show_main_ui()
                    self.refresh_groups()
                
                self.after(1000, _proceed)
            else:
                self.after(100, self._wait_for_login, future)
        except errors.SessionPasswordNeededError:
            self.login_log_lbl.configure(text="2FA password required.", text_color=WIN11["warning"])
        except Exception as e:
            self.login_log_lbl.configure(text=f"Login Error: {e}", text_color=WIN11["danger"])

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN UI  (Sidebar + Content pane)
    # ─────────────────────────────────────────────────────────────────────────
    def show_main_ui(self):
        if hasattr(self, 'login_frame') and self.login_frame.winfo_exists():
            self.login_frame.destroy()

        # ── Sidebar ──────────────────────────────────────────────────────────
        self.sidebar = ctk.CTkFrame(
            self, width=210, corner_radius=0,
            fg_color=WIN11["sidebar_bg"],
            border_width=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)

        # Branding
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(28, 20))
        
        self.side_logo = ctk.CTkLabel(brand, text="✈", font=(FONT_FAMILY, 24), text_color=WIN11["accent"])
        self.side_logo.pack(side="left")
        self._load_image_to_label(self.side_logo, (24, 24))
        
        ctk.CTkLabel(brand, text="  Broadcaster", font=(FONT_FAMILY, 15, "bold"),
                     text_color=WIN11["text_primary"]).pack(side="left")

        ctk.CTkFrame(self.sidebar, height=1, fg_color=WIN11["border"]).pack(fill="x", padx=16, pady=(0, 12))

        # Nav items  (label, tab_name, emoji)
        self._nav_buttons = {}
        nav_items = [
            ("Broadcast",    "broadcast",  "📡"),
            ("Drafts",       "drafts",     "📝"),
            ("System Logs",  "logs",       "🗒️"),
            ("Settings",     "settings",   "⚙"),
        ]
        for label, key, icon in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=f"  {icon}  {label}",
                anchor="w", height=40, corner_radius=8,
                fg_color="transparent",
                hover_color=WIN11["sidebar_active"],
                text_color=WIN11["text_secondary"],
                font=(FONT_FAMILY, 13),
                command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[key] = btn

        # Logout at bottom
        ctk.CTkFrame(self.sidebar, height=1, fg_color=WIN11["border"]).pack(fill="x", padx=16, side="bottom", pady=12)
        make_button(self.sidebar, "Sign Out", command=self.logout,
                    style="ghost", width=170, height=36).pack(side="bottom", padx=20, pady=(0, 8))

        # ── Content pane ─────────────────────────────────────────────────────
        self.content = ctk.CTkFrame(self, fg_color=WIN11["bg_base"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        # Build all tab frames (hidden by default)
        self._frames = {}
        for _, key, _ in nav_items:
            f = ctk.CTkFrame(self.content, fg_color=WIN11["bg_base"], corner_radius=0)
            f.grid(row=0, column=0, sticky="nsew")
            self._frames[key] = f

        self._build_broadcast_tab(self._frames["broadcast"])
        self._build_drafts_tab(self._frames["drafts"])
        self._build_logs_tab(self._frames["logs"])
        self._build_settings_tab(self._frames["settings"])

        # Start on Broadcast
        self._switch_tab("broadcast")
        self.update_slowmode_countdowns()

    def _switch_tab(self, key: str):
        for k, f in self._frames.items():
            f.grid_remove()
        self._frames[key].grid()

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=WIN11["sidebar_active"], text_color=WIN11["text_primary"])
            else:
                btn.configure(fg_color="transparent", text_color=WIN11["text_secondary"])
        self._active_nav = key

    # ─────────────────────────────────────────────────────────────────────────
    # BROADCAST TAB
    # ─────────────────────────────────────────────────────────────────────────
    def _build_broadcast_tab(self, parent):
        parent.grid_columnconfigure(0, weight=3)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(0, weight=1)

        # ── Left column ───────────────────────────────────────────────────────
        left = ctk.CTkFrame(parent, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(20, 10), pady=20)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # Page header
        hdr = ctk.CTkFrame(left, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        make_heading(hdr, "Message Composition", 16).pack(side="left")

        # Message card
        msg_card = make_card(left)
        msg_card.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        msg_card.grid_rowconfigure(1, weight=1)
        msg_card.grid_columnconfigure(0, weight=1)

        make_section_label(msg_card, "MESSAGE CONTENT").grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        self.message_box = ctk.CTkTextbox(
            msg_card,
            font=(FONT_FAMILY, 12),
            fg_color=WIN11["bg_input"],
            border_width=1,
            border_color=WIN11["border"],
            corner_radius=6,
            text_color=WIN11["text_primary"],
            wrap="word",
        )
        self.message_box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.message_box.bind("<KeyRelease>", self._on_message_modified)

        # Message Actions Row
        msg_actions = ctk.CTkFrame(msg_card, fg_color="transparent")
        msg_actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        
        self.save_msg_btn = make_button(msg_actions, "💾  Save as Template",
                    command=self.save_draft, style="accent", width=170, height=32)
        self.save_msg_btn.pack(side="left", padx=(0, 10))
        
        make_button(msg_actions, "Clear Box",
                    command=self.clear_message_box,
                    style="neutral", width=100, height=32).pack(side="left")

        # ── Settings card ─────────────────────────────────────────────────────
        ctrl_card = make_card(left)
        ctrl_card.grid(row=3, column=0, sticky="ew", pady=(0, 12))

        make_heading(ctrl_card, "Broadcast Settings", 13).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(14, 10))

        # Toggles row
        toggles = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        toggles.grid(row=1, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 10))

        self.unique_mode_var = ctk.BooleanVar(value=False)
        self.safe_mode_var   = ctk.BooleanVar(value=True)

        for var, label in [(self.unique_mode_var, "SpinTax"), (self.safe_mode_var, "Safe Mode")]:
            ctk.CTkSwitch(
                toggles, text=label, variable=var,
                font=(FONT_FAMILY, 12),
                button_color=WIN11["accent"],
                button_hover_color=WIN11["accent_hover"],
                progress_color=WIN11["accent"],
                text_color=WIN11["text_primary"],
            ).pack(side="left", padx=(0, 24))

        # Timing row
        timing = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        timing.grid(row=2, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 16))

        for lbl, default in [("Interval (s)", "30"), ("Duration (m)", "60")]:
            grp = ctk.CTkFrame(timing, fg_color="transparent")
            grp.pack(side="left", padx=(0, 24))
            make_section_label(grp, lbl.upper()).pack(anchor="w")
            e = make_entry(grp, "", width=80)
            e.insert(0, default)
            e.pack()
            if "Interval" in lbl:
                self.interval_entry = e
            else:
                self.duration_entry = e

        # Progress + action
        self.progress_bar = ctk.CTkProgressBar(
            left, height=6, corner_radius=3,
            fg_color=WIN11["bg_input"],
            progress_color=WIN11["accent"],
        )
        self.progress_bar.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        self.progress_bar.set(0)

        self.start_btn = make_button(
            left, "▶  Start Broadcast",
            command=self.start_broadcast,
            style="accent", height=44, width=0,
        )
        self.start_btn.configure(font=(FONT_FAMILY, 14, "bold"))
        self.start_btn.grid(row=5, column=0, sticky="ew")

        # ── Right column – Groups ──────────────────────────────────────────────
        right = make_card(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=20)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        make_heading(right, "Target Groups", 15).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        # Toolbar
        toolbar = ctk.CTkFrame(right, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))

        make_button(toolbar, "⟳  Refresh", command=self.refresh_groups,
                    style="neutral", width=100, height=30).pack(side="left", padx=(0, 6))

        self.apply_bl_btn = make_button(toolbar, "Apply Block List",
                                         command=self.apply_blacklist,
                                         style="neutral", width=130, height=30)
        self.apply_bl_btn.pack(side="left")

        # Select all
        self.select_all_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            right, text="Select / Deselect All",
            variable=self.select_all_var,
            command=self.toggle_all_groups,
            font=(FONT_FAMILY, 12),
            text_color=WIN11["text_primary"],
            fg_color=WIN11["accent"],
            hover_color=WIN11["accent_hover"],
            border_color=WIN11["border"],
            corner_radius=4,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 8))

        self.groups_scroll = ctk.CTkScrollableFrame(
            right, fg_color="transparent",
            scrollbar_button_color=WIN11["bg_hover"],
            scrollbar_button_hover_color=WIN11["accent"],
        )
        self.groups_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 12))

    # ─────────────────────────────────────────────────────────────────────────
    # DRAFTS TAB
    # ─────────────────────────────────────────────────────────────────────────
    def _build_drafts_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        make_heading(parent, "Message Templates", 16).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 4))
        make_section_label(parent, "Save and reuse frequently used messages").grid(
            row=0, column=0, sticky="sw", padx=24, pady=(24, 0))

        self.drafts_scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent",
            scrollbar_button_color=WIN11["bg_hover"],
            scrollbar_button_hover_color=WIN11["accent"],
        )
        self.drafts_scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(12, 0))

        self.update_drafts_list()

    def update_drafts_list(self):
        for widget in self.drafts_scroll.winfo_children():
            widget.destroy()
        self.current_edit_index = None

        if not self.drafts:
            ctk.CTkLabel(
                self.drafts_scroll, text="No drafts yet. Compose a message and save it.",
                font=(FONT_FAMILY, 12), text_color=WIN11["text_disabled"]
            ).pack(pady=40)
            return

        for idx, draft in enumerate(self.drafts):
            card = make_card(self.drafts_scroll)
            card.pack(fill="x", pady=4)

            preview = (draft[:80] + "…") if len(draft) > 80 else draft
            ctk.CTkLabel(card, text=preview, font=(FONT_FAMILY, 12),
                         text_color=WIN11["text_secondary"],
                         anchor="w", justify="left", wraplength=420).pack(
                side="left", padx=14, pady=12, fill="x", expand=True)

            btn_grp = ctk.CTkFrame(card, fg_color="transparent")
            btn_grp.pack(side="right", padx=10)

            make_button(btn_grp, "Load", width=60, height=28,
                        style="neutral",
                        command=lambda t=draft, i=idx: self.load_draft_text(t, i)).pack(side="left", padx=4)
            make_button(btn_grp, "✕", width=36, height=28,
                        style="danger",
                        command=lambda i=idx: self.delete_draft(i)).pack(side="left")

    def save_draft(self):
        text = self.message_box.get("1.0", "end-1c").strip()
        if not text:
            return
        if hasattr(self, 'current_edit_index') and self.current_edit_index is not None:
            self.drafts[self.current_edit_index] = text
            self.current_edit_index = None
            self.log_message("Draft updated.")
        elif text not in self.drafts:
            self.drafts.append(text)
            self.log_message("Draft saved.")
        else:
            self.log_message("Draft already exists.")
        self.save_drafts_local()
        self.update_drafts_list()

    def delete_draft(self, index):
        if 0 <= index < len(self.drafts):
            self.drafts.pop(index)
            self.save_drafts_local()
            self.update_drafts_list()
            self.log_message("Draft deleted.")
            self.current_edit_index = None

    def load_draft_text(self, text, index=None):
        self.message_box.delete("1.0", "end")
        self.message_box.insert("1.0", text)
        self.current_edit_index = index
        self._set_save_button_state("accent") # Reset to normal
        self._switch_tab("broadcast")
        if index is not None:
            self.log_message(f"Loaded draft #{index + 1} for editing.")

    def clear_message_box(self):
        self.message_box.delete("1.0", "end")
        self.current_edit_index = None
        self._set_save_button_state("accent")

    def _on_message_modified(self, event=None):
        if self.current_edit_index is not None:
            # We are editing a draft, change button color to show unsaved changes
            self._set_save_button_state("success")
        else:
            # New message
            self._set_save_button_state("accent")

    def _set_save_button_state(self, style):
        if not hasattr(self, 'save_msg_btn'): return
        
        if style == "success":
            self.save_msg_btn.configure(fg_color=WIN11["success"], 
                                      hover_color=WIN11["success_hover"],
                                      text="💾  Save Changes")
        else:
            self.save_msg_btn.configure(fg_color=WIN11["accent"], 
                                      hover_color=WIN11["accent_hover"],
                                      text="💾  Save as Template")

    # ─────────────────────────────────────────────────────────────────────────
    # LOGS TAB
    # ─────────────────────────────────────────────────────────────────────────
    def _build_logs_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 12))
        make_heading(hdr, "System Logs", 16).pack(side="left")
        make_button(hdr, "Clear", command=self.clear_logs_ui,
                    style="neutral", width=80, height=30).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            parent,
            font=("Consolas", 11),
            fg_color=WIN11["bg_surface"],
            border_width=1, border_color=WIN11["border"],
            corner_radius=8,
            text_color="#7EC8A2",         # terminal green tint
            activate_scrollbars=True,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.log_box.configure(state="disabled")

    def clear_logs_ui(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ─────────────────────────────────────────────────────────────────────────
    # SETTINGS TAB
    # ─────────────────────────────────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)

        make_heading(parent, "Settings", 16).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 16))

        container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        container.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        parent.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # ── Update card ──────────────────────────────────────────────────────
        uc = make_card(container)
        uc.pack(fill="x", pady=(0, 12))

        r = ctk.CTkFrame(uc, fg_color="transparent")
        r.pack(fill="x", padx=20, pady=16)
        icon_col = ctk.CTkFrame(r, fg_color="transparent", width=40)
        icon_col.pack(side="left")
        ctk.CTkLabel(icon_col, text="🔄", font=(FONT_FAMILY, 20)).pack()
        txt_col = ctk.CTkFrame(r, fg_color="transparent")
        txt_col.pack(side="left", padx=12, fill="x", expand=True)
        make_heading(txt_col, "Software Updates").pack(anchor="w")
        make_section_label(txt_col, "Check GitHub for the latest release").pack(anchor="w")
        make_button(r, "Check Now", command=self.check_for_updates,
                    style="neutral", width=110, height=34).pack(side="right")

        # ── Bug report card ──────────────────────────────────────────────────
        bc = make_card(container)
        bc.pack(fill="x", pady=(0, 12))

        r2 = ctk.CTkFrame(bc, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(r2, text="🐛", font=(FONT_FAMILY, 20)).pack(side="left")
        txt2 = ctk.CTkFrame(r2, fg_color="transparent")
        txt2.pack(side="left", padx=12, fill="x", expand=True)
        make_heading(txt2, "Bug Reports & Feature Requests").pack(anchor="w")
        make_section_label(txt2, "Open an issue on GitHub").pack(anchor="w")
        make_button(r2, "Open GitHub", command=self.report_bug,
                    style="ghost", width=110, height=34).pack(side="right")

        # ── Account card ─────────────────────────────────────────────────────
        ac = make_card(container)
        ac.pack(fill="x", pady=(0, 12))

        r3 = ctk.CTkFrame(ac, fg_color="transparent")
        r3.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(r3, text="👤", font=(FONT_FAMILY, 20)).pack(side="left")
        txt3 = ctk.CTkFrame(r3, fg_color="transparent")
        txt3.pack(side="left", padx=12, fill="x", expand=True)
        make_heading(txt3, "Account").pack(anchor="w")
        make_section_label(txt3, "Sign out and remove local session").pack(anchor="w")
        make_button(r3, "Sign Out", command=self.logout,
                    style="danger", width=100, height=34).pack(side="right")

    # ─────────────────────────────────────────────────────────────────────────
    # Broadcast logic
    # ─────────────────────────────────────────────────────────────────────────
    def start_broadcast(self):
        if self.is_broadcasting:
            self.is_broadcasting = False
            self.start_btn.configure(text="▶  Start Broadcast",
                                     fg_color=WIN11["accent"],
                                     hover_color=WIN11["accent_hover"])
            self.log_message("Stopping broadcast…")
            return

        message = self.message_box.get("1.0", "end-1c").strip()
        if not message:
            self.log_message("Error: Message is empty.")
            return

        target_ids = [gid for gid, var in self.group_vars.items() if var.get()]
        if not target_ids:
            self.log_message("Error: No groups selected.")
            return

        try:
            interval = int(self.interval_entry.get())
            duration = int(self.duration_entry.get())
        except ValueError:
            self.log_message("Error: Invalid interval or duration.")
            return

        self.is_broadcasting = True
        self.start_btn.configure(text="⏹  Stop Broadcast",
                                  fg_color=WIN11["danger"],
                                  hover_color=WIN11["danger_hover"])
        self.log_message(f"Starting broadcast to {len(target_ids)} groups…")
        threading.Thread(
            target=self._broadcast_task,
            args=(target_ids, message, interval, duration),
            daemon=True,
        ).start()

    def _broadcast_task(self, target_ids, message, user_interval, duration_min):
        start_time = time.time()
        end_time   = start_time + (duration_min * 60)
        is_unique  = self.unique_mode_var.get()
        is_safe    = self.safe_mode_var.get()

        effective_interval = max(user_interval, 60) if is_safe else user_interval
        if is_safe:
            self.log_message(f"Safe Mode ON: effective interval = {effective_interval}s")

        while self.is_broadcasting and time.time() < end_time:
            sent_in_this_loop = 0

            current_targets = [g for g in self.groups if g['id'] in target_ids]
            current_targets.sort(key=lambda g: g.get('slowmode_until', 0))

            for grp in current_targets:
                if not self.is_broadcasting:
                    break

                gid = grp['id']
                now  = time.time()
                last = self.group_last_sent.get(gid, 0)

                if (now - last) < effective_interval:
                    continue
                if grp.get('slowmode_until', 0) > 0:
                    continue

                try:
                    msg_to_send = parse_spintax(message) if is_unique else message
                    self.log_message(f"Sending → {grp['title']}…")
                    future = self.manager.send_message(gid, msg_to_send)

                    res_start = time.time()
                    while not future.done() and time.time() - res_start < 10:
                        time.sleep(0.1)

                    if future.done():
                        future.result()
                        self.log_message(f"✓ Sent → {grp['title']}")
                        self.group_last_sent[gid] = time.time()
                        grp['slowmode_until'] = grp.get('slowmode', 0)
                        sent_in_this_loop += 1
                        self.progress_bar.set((target_ids.index(gid) + 1) / len(target_ids))
                    else:
                        self.log_message(f"Timeout → {grp['title']}")

                except errors.SlowModeWaitError as e:
                    self.log_message(f"SlowMode → {grp['title']}: wait {e.seconds}s")
                    grp['slowmode_until'] = e.seconds
                except Exception as e:
                    self.log_message(f"Failed → {grp['title']}: {e}")

                time.sleep(random.uniform(1, 3))

            if sent_in_this_loop == 0:
                remaining = int(end_time - time.time())
                if remaining > 0:
                    time.sleep(5)

        self.log_message("Broadcast session ended.")
        self.is_broadcasting = False
        self.start_btn.configure(text="▶  Start Broadcast",
                                  fg_color=WIN11["accent"],
                                  hover_color=WIN11["accent_hover"])
        self.progress_bar.set(0)

    # ─────────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────────
    def check_for_updates(self):
        def _check():
            try:
                url = "https://api.github.com/repos/khan-zero/Broadcaster/releases/latest"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    version = data.get("tag_name", "Unknown")
                    self.log_message(f"Latest version: {version}")
                    self.show_info("Update Check", f"Latest GitHub release: {version}")
                else:
                    self.log_message("Update check failed: repo not found or private.")
            except Exception as e:
                self.log_message(f"Update check error: {e}")
        threading.Thread(target=_check, daemon=True).start()

    def report_bug(self):
        webbrowser.open("https://github.com/khan-zero/Broadcaster/issues")

    def logout(self, force=False):
        def _exec_logout(confirmed):
            if not confirmed: return
            try:
                if self.manager.client and self.manager.phone:
                    try:
                        self.manager.loop_thread.run_coroutine(self.manager.client.disconnect())
                    except Exception:
                        pass
                    if not force:
                        session_file = os.path.join(SESSIONS_DIR, f"{self.manager.phone}.session")
                        if os.path.exists(session_file):
                            try:
                                os.remove(session_file)
                            except Exception:
                                pass
                self.destroy()
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                self.destroy()

        if force:
            _exec_logout(True)
        else:
            self.ask_yes_no("Sign Out", "Are you sure you want to sign out?", _exec_logout)

    def save_groups_local(self, groups):
        try:
            with open(GROUPS_FILE, "w") as f:
                json.dump(groups, f)
        except Exception as e:
            self.log_message(f"Failed to save groups.json: {e}")

    def load_drafts(self):
        if os.path.exists(DRAFTS_FILE):
            try:
                with open(DRAFTS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_drafts_local(self):
        try:
            with open(DRAFTS_FILE, "w") as f:
                json.dump(self.drafts, f)
        except Exception as e:
            self.log_message(f"Failed to save drafts: {e}")

    def load_blacklist_local(self):
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    return set(json.load(f))
            except Exception:
                return set()
        return set()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def _load_image_to_label(self, label, size):
        try:
            from PIL import Image
            if os.path.exists("app_logo_image.png"):
                img = ctk.CTkImage(light_image=Image.open("app_logo_image.png"),
                                  dark_image=Image.open("app_logo_image.png"),
                                  size=size)
                label.configure(image=img, text="")
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = None
    try:
        app = App()
        app.report_callback_exception = app.handle_exception
        app.mainloop()
    except Exception as e:
        err_msg = traceback.format_exc()
        logging.error(f"Critical Startup Error: {err_msg}")

        root = tk.Tk()
        root.withdraw()
        tkinter.messagebox.showerror(
            "Critical Error",
            f"Application failed to start.\n\n{e}\n\nCheck error_log.txt for details."
        )
        root.destroy()

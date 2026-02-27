import os
import sys
import logging
import traceback
import threading
import time
import json
import random
import re
import webbrowser
from datetime import datetime
import customtkinter as ctk
from PIL import Image, ImageTk

from src.core.config import (
    Config, WIN11, FONT_FAMILY, APP_LOGO_PATH, ERROR_LOG_FILE, 
    GROUPS_FILE, DRAFTS_FILE, BLACKLIST_FILE, SESSIONS_DIR, SETTINGS_FILE
)
from src.core.telegram_manager import TelegramManager
from src.ui.components.widgets import (
    make_card, make_section_label, make_heading, make_button, make_entry
)
from src.utils.helpers import parse_spintax

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self._setup_logging()
        
        self.title("Telegram Broadcaster Pro")
        self.geometry("1160x720")
        self.minsize(900, 600)
        self.configure(fg_color=WIN11["bg_base"])
        self._set_app_icon()

        self.manager = TelegramManager(self.config, self._safe_log)
        
        # Verify or Prompt for API Credentials
        if not self.config.api_id or not self.config.api_hash:
            self._request_api_credentials()
            if not self.config.api_id or not self.config.api_hash:
                # Still missing, show error and potentially exit or wait
                self.after(500, lambda: self.log_message("Error: API Keys are required."))
        
        # State
        self.groups = []
        self.group_vars = {}
        self.slowmode_labels = {}
        self.bl_buttons = {}
        self.is_broadcasting = False
        self.group_last_sent = {}
        self.drafts = self._load_drafts()
        self.pending_blacklist = self._load_blacklist()
        self.current_edit_index = None
        
        # UI Setup
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.withdraw()
        self._check_initial_login()

    def _setup_logging(self):
        logging.basicConfig(
            filename=ERROR_LOG_FILE,
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

    def _set_app_icon(self):
        try:
            if os.path.exists(APP_LOGO_PATH):
                img = Image.open(APP_LOGO_PATH)
                img = img.resize((64, 64), Image.LANCZOS)
                self.iconphoto(False, ImageTk.PhotoImage(img))
        except Exception as e:
            print(f"Failed to set icon: {e}")

    def _safe_log(self, message):
        self.after(0, lambda: self.log_message(message))

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}]  {message}\n"
        if hasattr(self, 'log_box'):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", full_msg)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

    def _check_initial_login(self):
        phone = self.config.get_last_phone()
        future = self.manager.connect(phone)
        self.after(1000, self._process_connection, future)

    def _process_connection(self, future):
        if not future.done():
            self.after(500, self._process_connection, future)
            return
        
        try:
            future.result()
            auth_future = self.manager.is_user_authorized()
            self.after(500, self._process_auth, auth_future)
        except Exception as e:
            self.log_message(f"Connection error: {e}")
            self.deiconify()
            self.create_login_ui()

    def _process_auth(self, future):
        if not future.done():
            self.after(500, self._process_auth, future)
            return
        
        self.deiconify()
        try:
            if future.result():
                self.show_main_ui()
                self.refresh_groups()
            else:
                self.create_login_ui()
        except Exception as e:
            self.log_message(f"Auth error: {e}")
            self.create_login_ui()

    # --- UI Building ---
    def create_login_ui(self):
        for widget in self.winfo_children(): widget.destroy()
        
        self.login_bg = ctk.CTkFrame(self, fg_color=WIN11["bg_base"])
        self.login_bg.place(relx=0, rely=0, relwidth=1, relheight=1)

        card = make_card(self, width=380)
        card.place(relx=0.5, rely=0.5, anchor="center")
        
        make_heading(card, "Telegram Broadcaster Pro", 18).pack(pady=(20, 2))
        make_section_label(card, "Sign in to your Telegram account").pack(pady=(0, 20))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=28, pady=20)

        self.phone_entry = make_entry(inner, "+1 234 567 8900", width=320)
        self.phone_entry.pack(fill="x")

        self.send_code_btn = make_button(inner, "Send Code", command=self.on_send_code, width=320)
        self.send_code_btn.pack(pady=10)

        self.code_entry = make_entry(inner, "Code", width=320)
        self.password_entry = make_entry(inner, "2FA Password", width=320, show="•")
        self.login_btn = make_button(inner, "Sign In", command=self.on_login, style="success", width=320)

    def on_send_code(self):
        phone = self.phone_entry.get().strip()
        if not phone: return
        self.config.set_last_phone(phone)
        future = self.manager.send_code_request(phone)
        self.after(100, self._wait_for_code, future)

    def _wait_for_code(self, future):
        if future.done():
            try:
                future.result()
                self.code_entry.pack(pady=5)
                self.password_entry.pack(pady=5)
                self.login_btn.pack(pady=10)
                self.send_code_btn.configure(state="disabled", text="Code Sent")
            except Exception as e:
                self.log_message(f"Error sending code: {e}")
        else:
            self.after(100, self._wait_for_code, future)

    def on_login(self):
        code = self.code_entry.get()
        password = self.password_entry.get()
        future = self.manager.sign_in(code, password or None)
        self.after(100, self._wait_for_login, future)

    def _wait_for_login(self, future):
        if future.done():
            try:
                future.result()
                for widget in self.winfo_children(): widget.destroy()
                self.show_main_ui()
                self.refresh_groups()
            except Exception as e:
                self.log_message(f"Login failed: {e}")
        else:
            self.after(100, self._wait_for_login, future)

    def show_main_ui(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=200, fg_color=WIN11["sidebar_bg"], corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(28, 20))
        make_heading(brand, "  Broadcaster", 15).pack(side="left")

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

        # Content pane
        self.content = ctk.CTkFrame(self, fg_color=WIN11["bg_base"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._frames = {}
        for _, key, _ in nav_items:
            f = ctk.CTkFrame(self.content, fg_color=WIN11["bg_base"], corner_radius=0)
            f.grid(row=0, column=0, sticky="nsew")
            self._frames[key] = f

        self._build_broadcast_tab(self._frames["broadcast"])
        self._build_drafts_tab(self._frames["drafts"])
        self._build_logs_tab(self._frames["logs"])
        self._build_settings_tab(self._frames["settings"])
        
        self._switch_tab("broadcast")
        self.update_slowmode_countdowns()

    def _switch_tab(self, key):
        for k, f in self._frames.items():
            f.grid_remove()
        self._frames[key].grid()
        for k, btn in self._nav_buttons.items():
            btn.configure(fg_color=WIN11["sidebar_active"] if k == key else "transparent",
                          text_color=WIN11["text_primary"] if k == key else WIN11["text_secondary"])

    def _build_broadcast_tab(self, parent):
        parent.grid_columnconfigure(0, weight=3)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(0, weight=1)

        # Left Column: Message Composition
        left = ctk.CTkFrame(parent, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        make_heading(left, "Message Composition", 16).grid(row=0, column=0, sticky="w", pady=(0, 10))
        
        msg_card = make_card(left)
        msg_card.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        msg_card.grid_rowconfigure(1, weight=1)
        msg_card.grid_columnconfigure(0, weight=1)

        make_section_label(msg_card, "MESSAGE CONTENT").grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        self.message_box = ctk.CTkTextbox(msg_card, fg_color=WIN11["bg_input"], border_width=1, border_color=WIN11["border"])
        self.message_box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))

        btn_row = ctk.CTkFrame(msg_card, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        make_button(btn_row, "Save as Template", command=self.save_draft, width=150).pack(side="left", padx=(0, 10))
        make_button(btn_row, "Clear", command=lambda: self.message_box.delete("1.0", "end"), style="neutral", width=80).pack(side="left")

        # Broadcast Settings
        ctrl_card = make_card(left)
        ctrl_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        
        settings_frame = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        settings_frame.pack(fill="x", padx=16, pady=16)

        self.unique_mode_var = ctk.BooleanVar(value=False)
        self.safe_mode_var = ctk.BooleanVar(value=True)
        
        ctk.CTkSwitch(settings_frame, text="SpinTax", variable=self.unique_mode_var).pack(side="left", padx=(0, 20))
        ctk.CTkSwitch(settings_frame, text="Safe Mode", variable=self.safe_mode_var).pack(side="left", padx=(0, 20))

        self.interval_entry = make_entry(settings_frame, "30", width=60)
        self.interval_entry.insert(0, "30")
        self.interval_entry.pack(side="left", padx=5)
        make_section_label(settings_frame, "Interval (s)").pack(side="left", padx=(0, 20))

        self.duration_entry = make_entry(settings_frame, "60", width=60)
        self.duration_entry.insert(0, "60")
        self.duration_entry.pack(side="left", padx=5)
        make_section_label(settings_frame, "Duration (m)").pack(side="left")

        self.start_btn = make_button(left, "Start Broadcast", command=self.start_broadcast, height=44)
        self.start_btn.grid(row=3, column=0, sticky="ew")

        # Right Column: Groups
        right = make_card(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=20)
        right.grid_rowconfigure(3, weight=1)  # Only the scroll frame should expand
        right.grid_columnconfigure(0, weight=1)

        make_heading(right, "Target Groups", 15).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        
        toolbar = ctk.CTkFrame(right, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        make_button(toolbar, "Refresh", command=self.refresh_groups, style="neutral", width=80, height=28).pack(side="left", padx=(0, 6))
        
        self.apply_bl_btn = make_button(toolbar, "Apply Block List", command=self.apply_blacklist, style="neutral", width=120, height=28)
        self.apply_bl_btn.pack(side="left")

        # Select all checkbox
        self.select_all_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(right, text="Select All", variable=self.select_all_var, 
                        command=self.toggle_all_groups, font=(FONT_FAMILY, 12),
                        border_width=1, corner_radius=4).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 8))
        
        self.groups_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.groups_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 12))

    def _build_drafts_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        make_heading(parent, "Templates", 16).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 12))
        self.drafts_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.drafts_scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self._update_drafts_list()

    def _build_logs_tab(self, parent):
        self.log_box = ctk.CTkTextbox(parent, fg_color=WIN11["bg_surface"], font=("Consolas", 11))
        self.log_box.pack(fill="both", expand=True, padx=20, pady=20)
        self.log_box.configure(state="disabled")

    def _build_settings_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        make_heading(parent, "Settings", 16).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 16))
        
        container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        container.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        parent.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # Update Card
        uc = make_card(container)
        uc.pack(fill="x", pady=(0, 12))
        r1 = ctk.CTkFrame(uc, fg_color="transparent")
        r1.pack(fill="x", padx=20, pady=16)
        txt1 = ctk.CTkFrame(r1, fg_color="transparent")
        txt1.pack(side="left", fill="x", expand=True)
        make_heading(txt1, "Software Updates").pack(anchor="w")
        make_section_label(txt1, "Check for latest release on GitHub").pack(anchor="w")
        make_button(r1, "Check Now", command=self.check_for_updates, style="neutral", width=110).pack(side="right")

        # Bug Report Card
        bc = make_card(container)
        bc.pack(fill="x", pady=(0, 12))
        r2 = ctk.CTkFrame(bc, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=16)
        txt2 = ctk.CTkFrame(r2, fg_color="transparent")
        txt2.pack(side="left", fill="x", expand=True)
        make_heading(txt2, "Bug Reports").pack(anchor="w")
        make_section_label(txt2, "Report issues or request features").pack(anchor="w")
        make_button(r2, "Open GitHub", command=self.report_bug, style="ghost", width=110).pack(side="right")

        # Logout Card
        ac = make_card(container)
        ac.pack(fill="x", pady=(0, 12))
        r3 = ctk.CTkFrame(ac, fg_color="transparent")
        r3.pack(fill="x", padx=20, pady=16)
        txt3 = ctk.CTkFrame(r3, fg_color="transparent")
        txt3.pack(side="left", fill="x", expand=True)
        make_heading(txt3, "Account").pack(anchor="w")
        make_section_label(txt3, "Sign out and reset session").pack(anchor="w")
        make_button(r3, "Sign Out", command=self.logout, style="danger", width=110).pack(side="right")

    # --- Logic ---
    def refresh_groups(self):
        self.log_message("Refreshing groups...")
        future = self.manager.get_dialogs()
        self.after(100, self._wait_for_groups, future)

    def _wait_for_groups(self, future):
        if future.done():
            try:
                self.groups = future.result()
                self._populate_groups_list()
                self.log_message(f"Found {len(self.groups)} groups")
            except Exception as e:
                self.log_message(f"Error fetching groups: {e}")
        else:
            self.after(100, self._wait_for_groups, future)

    def _populate_groups_list(self):
        if not hasattr(self, 'groups_scroll') or not self.groups_scroll.winfo_exists():
            return
        
        for widget in self.groups_scroll.winfo_children(): widget.destroy()
        self.group_vars.clear()
        self.slowmode_labels.clear()
        self.bl_buttons.clear()

        # Sort groups by slowmode
        sorted_groups = sorted(self.groups, key=lambda g: g.get('slowmode_until', 0), reverse=True)

        for grp in sorted_groups:
            gid = grp['id']
            is_blacklisted = gid in self.pending_blacklist

            row = ctk.CTkFrame(self.groups_scroll, fg_color=WIN11["bg_surface"], corner_radius=6, border_width=1, border_color=WIN11["border"])
            row.pack(fill="x", pady=2, padx=2)
            
            var = ctk.BooleanVar()
            chk = ctk.CTkCheckBox(
                row, text=grp['title'], variable=var,
                text_color=WIN11["text_disabled"] if is_blacklisted else WIN11["text_primary"]
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
                sm_lbl = ctk.CTkLabel(row, text=badge_txt, font=(FONT_FAMILY, 10), text_color=WIN11["warning"], fg_color=WIN11["bg_overlay"], corner_radius=4, padx=6, pady=2)
                sm_lbl.pack(side="right", padx=(4, 6))
                self.slowmode_labels[gid] = sm_lbl

            # Blacklist toggle
            bl_text = "✓ Listed" if is_blacklisted else "Block"
            bl_style = "danger" if is_blacklisted else "neutral"
            bl_btn = make_button(row, bl_text, width=65, height=26, style=bl_style, command=lambda g=grp: self.toggle_blacklist_ui(g))
            bl_btn.pack(side="right", padx=4)
            self.bl_buttons[gid] = bl_btn

    def toggle_blacklist_ui(self, group):
        gid = group['id']
        if gid in self.pending_blacklist:
            self.pending_blacklist.remove(gid)
            self.bl_buttons[gid].configure(text="Block", fg_color=WIN11["bg_input"], hover_color=WIN11["bg_hover"])
        else:
            self.pending_blacklist.add(gid)
            self.bl_buttons[gid].configure(text="✓ Listed", fg_color=WIN11["danger"], hover_color=WIN11["danger_hover"])
        self.apply_bl_btn.configure(fg_color=WIN11["success"], hover_color=WIN11["success_hover"])

    def apply_blacklist(self):
        try:
            with open(BLACKLIST_FILE, "w") as f:
                json.dump(list(self.pending_blacklist), f)
            self.log_message("Blacklist saved.")
            self.apply_bl_btn.configure(fg_color=WIN11["bg_input"], hover_color=WIN11["bg_hover"])
            self.refresh_groups()
        except Exception as e:
            self.log_message(f"Failed to save blacklist: {e}")

    def toggle_all_groups(self):
        val = self.select_all_var.get()
        for var in self.group_vars.values():
            var.set(val)

    def update_slowmode_countdowns(self):
        if not self.winfo_exists(): return
        for gid, grp in [(g['id'], g) for g in self.groups if g['id'] in self.slowmode_labels]:
            if grp.get('slowmode_until', 0) > 0:
                grp['slowmode_until'] -= 1
                wait = grp['slowmode_until']
                self.slowmode_labels[gid].configure(text=f"⏱ {wait}s" if wait > 0 else f"⏱ {grp['slowmode']}s")
            elif grp.get('slowmode', 0) > 0:
                self.slowmode_labels[gid].configure(text=f"⏱ {grp['slowmode']}s")
        self.after(1000, self.update_slowmode_countdowns)

    def start_broadcast(self):
        if self.is_broadcasting:
            self.is_broadcasting = False
            self.start_btn.configure(text="Start Broadcast", fg_color=WIN11["accent"])
            return

        message = self.message_box.get("1.0", "end-1c").strip()
        if not message: return

        target_ids = [gid for gid, var in self.group_vars.items() if var.get()]
        if not target_ids: return

        try:
            interval = int(self.interval_entry.get())
            duration = int(self.duration_entry.get())
        except: return

        self.is_broadcasting = True
        self.start_btn.configure(text="Stop Broadcast", fg_color=WIN11["danger"])
        threading.Thread(target=self._broadcast_task, args=(target_ids, message, interval, duration), daemon=True).start()

    def _broadcast_task(self, target_ids, message, interval, duration_min):
        end_time = time.time() + (duration_min * 60)
        is_unique = self.unique_mode_var.get()
        is_safe = self.safe_mode_var.get()
        
        effective_interval = max(interval, 60) if is_safe else interval
        if is_safe:
            self.log_message(f"Safe Mode ON: Minimum interval set to {effective_interval}s")

        while self.is_broadcasting and time.time() < end_time:
            for gid in target_ids:
                if not self.is_broadcasting: break
                
                grp = next((g for g in self.groups if g['id'] == gid), None)
                if not grp: continue

                # Skip if in slowmode
                if grp.get('slowmode_until', 0) > 0:
                    continue

                self.log_message(f"Sending to {grp['title']}...")
                msg = parse_spintax(message) if is_unique else message
                future = self.manager.send_message(gid, msg)
                
                res_start = time.time()
                while not future.done() and time.time() - res_start < 10: time.sleep(0.1)
                
                if future.done():
                    try:
                        future.result()
                        self.log_message(f"✓ Sent: {grp['title']}")
                        grp['slowmode_until'] = grp.get('slowmode', 0) # Trigger slowmode timer
                    except Exception as e:
                        if "SlowModeWaitError" in str(e):
                            seconds = int(re.search(r'wait (\d+)', str(e)).group(1))
                            grp['slowmode_until'] = seconds
                            self.log_message(f"⏱ SlowMode: {grp['title']} (Wait {seconds}s)")
                        else:
                            self.log_message(f"Failed: {grp['title']} - {e}")
                
                time.sleep(random.uniform(1, 3)) # Human-like delay between groups
            
            time.sleep(effective_interval)

        self.is_broadcasting = False
        self.after(0, lambda: self.start_btn.configure(text="Start Broadcast", fg_color=WIN11["accent"]))

    def save_draft(self):
        text = self.message_box.get("1.0", "end-1c").strip()
        if text and text not in self.drafts:
            self.drafts.append(text)
            self._save_drafts()
            self._update_drafts_list()

    def _update_drafts_list(self):
        for widget in self.drafts_scroll.winfo_children(): widget.destroy()
        for i, draft in enumerate(self.drafts):
            card = make_card(self.drafts_scroll)
            card.pack(fill="x", pady=4)
            ctk.CTkLabel(card, text=draft[:50] + "...", anchor="w").pack(side="left", padx=10, pady=10)
            make_button(card, "Load", command=lambda t=draft: self._load_draft(t), width=60).pack(side="right", padx=5)

    def _load_draft(self, text):
        self.message_box.delete("1.0", "end")
        self.message_box.insert("1.0", text)
        self._switch_tab("broadcast")

    def logout(self):
        self.manager.disconnect()
        self.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _load_drafts(self):
        if os.path.exists(DRAFTS_FILE):
            try:
                with open(DRAFTS_FILE, "r") as f: return json.load(f)
            except: pass
        return []

    def _save_drafts(self):
        with open(DRAFTS_FILE, "w") as f: json.dump(self.drafts, f)

    def _load_blacklist(self):
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f: return set(json.load(f))
            except: pass
        return set()

    def check_for_updates(self):
        def _check():
            try:
                # IMPORTANT: Update this URL to match your repo
                url = "https://api.github.com/repos/khan-zero/Broadcaster/releases/latest"
                import requests
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    version = data.get("tag_name", "Unknown")
                    self.log_message(f"Latest version available: {version}")
                    from tkinter import messagebox
                    messagebox.showinfo("Update Check", f"Latest GitHub release: {version}")
                else:
                    self.log_message("Update check failed: Repository not found or private.")
            except Exception as e:
                self.log_message(f"Update check error: {e}")
        threading.Thread(target=_check, daemon=True).start()

    def report_bug(self):
        webbrowser.open("https://github.com/khan-zero/Broadcaster/issues")

    def _request_api_credentials(self):
        if not self.config.api_id:
            dialog = ctk.CTkInputDialog(text="Enter your Telegram API ID:", title="API Setup")
            val = dialog.get_input()
            if val:
                try:
                    self.config.api_id = int(val)
                    self.config.save_settings({"api_id": self.config.api_id})
                except ValueError:
                    pass
        
        if not self.config.api_hash:
            dialog = ctk.CTkInputDialog(text="Enter your Telegram API Hash:", title="API Setup")
            val = dialog.get_input()
            if val:
                self.config.api_hash = val
                self.config.save_settings({"api_hash": self.config.api_hash})

    def show_error(self, title, message):
        from tkinter import messagebox
        messagebox.showerror(title, message)

    def handle_exception(self, exc_type, exc_value, exc_traceback):
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logging.error(f"Unhandled Exception: {err_msg}")
        print(err_msg)

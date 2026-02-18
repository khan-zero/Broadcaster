import re
from datetime import datetime
from typing import List, Dict, Optional, Union

import customtkinter as ctk
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors
from telethon.tl.types import Dialog, InputPeerChannel, InputPeerChat, InputPeerUser, ChannelFull, ChatFull

# --- Load Environment ---
load_dotenv()

# --- Configuration ---
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_NAME = "userbot_session"
GROUPS_FILE = "groups.json"
DRAFTS_FILE = "drafts.json"

if API_ID:
    API_ID = int(API_ID)

# --- Theme & Style ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

def parse_spintax(text: str) -> str:
    """Parses spintax like {Hello|Hi|Hey} and picks a random value."""
    while True:
        match = re.search(r'\{([^{}]*)\}', text)
        if not match:
            break
        options = match.group(1).split('|')
        text = text[:match.start()] + random.choice(options) + text[match.end():]
    return text

class AsyncLoopThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coroutine(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

class TelegramManager:
    def __init__(self, loop_thread: AsyncLoopThread, log_callback):
        self.loop_thread = loop_thread
        self.log = log_callback
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH, loop=loop_thread.loop)
        self.phone = None
        self.is_connected = False

    def connect(self):
        # Starts the client connection (async)
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
        async for dialog in self.client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                entity = dialog.entity
                slowmode = getattr(entity, 'slowmode_seconds', 0)
                # For basic groups, slowmode might not be directly on entity, but userbot usually handles channels/megagroups
                groups.append({
                    "id": dialog.id,
                    "title": dialog.name,
                    "type": "channel" if dialog.is_channel else "group",
                    "slowmode": slowmode if slowmode else 0
                })
        return groups

    def send_message(self, entity_id, message):
        return self.loop_thread.run_coroutine(self.client.send_message(entity_id, message))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Telegram Broadcaster Pro")
        self.geometry("1100x700")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Initialize Backend
        self.loop_thread = AsyncLoopThread()
        self.loop_thread.start()
        self.manager = TelegramManager(self.loop_thread, self.log_message)
        
        # State
        self.groups = []
        self.selected_groups = set()
        self.drafts = self.load_drafts()
        
        # Check API credentials
        if not API_ID or not API_HASH:
            self.after(500, lambda: tkinter.messagebox.showerror("Error", "API_ID or API_HASH missing in .env file!\nUse .env.example to create one."))
            return

        # UI Setup
        self.create_login_ui()
        
        # Check login status on start
        self.check_initial_login()

    def check_initial_login(self):
        future = self.manager.connect()
        # We need to wait for connection result, then check auth
        # In a real app we'd use callbacks, here we poll or use dummy wait for simplicity in Tkinter
        self.after(1000, self._check_auth_after_connect, future)

    def _check_auth_after_connect(self, connect_future):
        if not connect_future.done():
            self.after(500, self._check_auth_after_connect, connect_future)
            return

        try:
            connect_future.result() # Raise exception if connection failed
            auth_future = self.manager.is_user_authorized()
            self.after(500, self._process_auth_result, auth_future)
        except Exception as e:
            self.log_message(f"Connection error: {e}")

    def _process_auth_result(self, auth_future):
        if not auth_future.done():
            self.after(500, self._process_auth_result, auth_future)
            return

        try:
            if auth_future.result():
                self.show_main_ui()
                self.log_message("Logged in automatically.")
                self.refresh_groups()
            else:
                self.log_message("Please log in.")
        except Exception as e:
            self.log_message(f"Auth check failed: {e}")

    def create_login_ui(self):
        self.login_frame = ctk.CTkFrame(self, corner_radius=15)
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(self.login_frame, text="Telegram Login", font=("Roboto Medium", 24)).pack(pady=20, padx=40)

        self.phone_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Phone Number (e.g., +1234567890)", width=250)
        self.phone_entry.pack(pady=10)

        self.send_code_btn = ctk.CTkButton(self.login_frame, text="Send Code", command=self.on_send_code)
        self.send_code_btn.pack(pady=10)

        self.code_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Verification Code", width=250)
        
        self.password_entry = ctk.CTkEntry(self.login_frame, placeholder_text="2FA Password (if enabled)", width=250, show="*")

        self.login_btn = ctk.CTkButton(self.login_frame, text="Login", command=self.on_login, fg_color="green")

        self.login_log_lbl = ctk.CTkLabel(self.login_frame, text="", text_color="gray")
        self.login_log_lbl.pack(pady=5)

    def on_send_code(self):
        phone = self.phone_entry.get()
        if not phone:
            self.login_log_lbl.configure(text="Please enter a phone number.")
            return
        
        self.login_log_lbl.configure(text="Sending code...")
        future = self.manager.send_code_request(phone)
        self.after(100, self._wait_for_code_req, future)

    def _wait_for_code_req(self, future):
        try:
            if future.done():
                future.result()
                self.login_log_lbl.configure(text="Code sent! Check your Telegram.")
                self.code_entry.pack(pady=10)
                self.password_entry.pack(pady=10)
                self.login_btn.pack(pady=20)
                self.send_code_btn.configure(state="disabled")
            else:
                self.after(100, self._wait_for_code_req, future)
        except Exception as e:
            self.login_log_lbl.configure(text=f"Error: {e}")

    def on_login(self):
        code = self.code_entry.get()
        password = self.password_entry.get()
        if not code:
            self.login_log_lbl.configure(text="Please enter the code.")
            return

        self.login_log_lbl.configure(text="Logging in...")
        future = self.manager.sign_in(code, password if password else None)
        self.after(100, self._wait_for_login, future)

    def _wait_for_login(self, future):
        try:
            if future.done():
                future.result()
                self.login_log_lbl.configure(text="Success!")
                self.login_frame.destroy()
                self.show_main_ui()
                self.refresh_groups()
            else:
                self.after(100, self._wait_for_login, future)
        except errors.SessionPasswordNeededError:
            self.login_log_lbl.configure(text="2FA Password Required.")
        except Exception as e:
            self.login_log_lbl.configure(text=f"Login Error: {e}")

    def show_main_ui(self):
        # Layout: 
        # Left: Saved Drafts List
        # Center: Message Composition & Broadcast Controls
        # Right: Group Selection
        # Bottom (spanning all): Log Console

        # --- Sidebar (Drafts) ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        
        ctk.CTkLabel(self.sidebar_frame, text="Drafts", font=("Roboto Medium", 18)).pack(pady=20)
        
        self.drafts_scroll = ctk.CTkScrollableFrame(self.sidebar_frame)
        self.drafts_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.update_drafts_list()
        
        ctk.CTkButton(self.sidebar_frame, text="Clear Message Box", command=lambda: self.message_box.delete("1.0", "end"), fg_color="gray").pack(pady=5, padx=10)
        ctk.CTkButton(self.sidebar_frame, text="Save Current as Draft", command=self.save_draft).pack(pady=5, padx=10)

        # --- Center (Message) ---
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.center_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

        ctk.CTkLabel(self.center_frame, text="Compose Message", font=("Roboto Medium", 18)).pack(anchor="w")
        
        self.message_box = ctk.CTkTextbox(self.center_frame, height=200, corner_radius=10)
        self.message_box.pack(fill="x", pady=(10, 20))

        ctk.CTkLabel(self.center_frame, text="Broadcast Controls", font=("Roboto Medium", 18)).pack(anchor="w")
        
        self.progress_bar = ctk.CTkProgressBar(self.center_frame)
        self.progress_bar.pack(fill="x", pady=10)
        self.progress_bar.set(0)

        self.start_btn = ctk.CTkButton(self.center_frame, text="START BROADCAST", height=50, font=("Roboto Medium", 16), command=self.start_broadcast)
        self.start_btn.pack(fill="x", pady=10)

        self.log_box = ctk.CTkTextbox(self.center_frame, height=150, activate_scrollbars=True)
        self.log_box.pack(fill="both", expand=True, pady=10)
        self.log_box.configure(state="disabled")

        self.unique_mode_var = ctk.BooleanVar(value=False)
        self.unique_switch = ctk.CTkSwitch(self.center_frame, text="Unique Message Mode (Spintax)", variable=self.unique_mode_var)
        self.unique_switch.pack(pady=5)

        # --- Right (Groups) ---
        self.right_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.right_frame.grid(row=0, column=2, sticky="nsew")

        ctk.CTkLabel(self.right_frame, text="Target Groups", font=("Roboto Medium", 18)).pack(pady=20)
        
        self.refresh_btn = ctk.CTkButton(self.right_frame, text="Refresh Groups", command=self.refresh_groups)
        self.refresh_btn.pack(pady=5, padx=10)

        self.select_all_var = ctk.BooleanVar(value=False)
        self.select_all_chk = ctk.CTkCheckBox(self.right_frame, text="Select/Deselect All", variable=self.select_all_var, command=self.toggle_all_groups)
        self.select_all_chk.pack(pady=5, padx=10)

        self.groups_scroll = ctk.CTkScrollableFrame(self.right_frame)
        self.groups_scroll.pack(fill="both", expand=True, padx=10, pady=10)

        self.group_vars = {} # id -> BooleanVar

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}\n"
        print(full_msg.strip())
        
        if hasattr(self, 'log_box'):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", full_msg)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

    def refresh_groups(self):
        self.log_message("Fetching groups...")
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
        # Clear existing
        for widget in self.groups_scroll.winfo_children():
            widget.destroy()
        self.group_vars.clear()

        for grp in groups:
            var = ctk.BooleanVar()
            label = grp['title']
            if grp.get('slowmode'):
                label += f" (Slow: {grp['slowmode']}s)"
            
            chk = ctk.CTkCheckBox(self.groups_scroll, text=label, variable=var)
            chk.pack(anchor="w", pady=2, padx=5)
            self.group_vars[grp['id']] = var

    def toggle_all_groups(self):
        val = self.select_all_var.get()
        for var in self.group_vars.values():
            var.set(val)

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
            except:
                return []
        return []

    def save_drafts_local(self):
        try:
            with open(DRAFTS_FILE, "w") as f:
                json.dump(self.drafts, f)
        except Exception as e:
            self.log_message(f"Failed to save drafts: {e}")

    def update_drafts_list(self):
        for widget in self.drafts_scroll.winfo_children():
            widget.destroy()
        
        for idx, draft in enumerate(self.drafts):
            frame = ctk.CTkFrame(self.drafts_scroll, fg_color="transparent")
            frame.pack(fill="x", pady=2)
            
            preview = (draft[:15] + '..') if len(draft) > 15 else draft
            
            # Label/Button for loading
            btn = ctk.CTkButton(frame, text=preview, 
                                command=lambda t=draft: self.load_draft_text(t),
                                fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"),
                                width=100)
            btn.pack(side="left", padx=2, fill="x", expand=True)
            
            # Delete button
            del_btn = ctk.CTkButton(frame, text="X", width=30, fg_color="#C0392B", hover_color="#922B21",
                                    command=lambda i=idx: self.delete_draft(i))
            del_btn.pack(side="right", padx=2)

    def save_draft(self):
        text = self.message_box.get("1.0", "end-1c").strip()
        if text:
            if text not in self.drafts:
                self.drafts.append(text)
                self.save_drafts_local()
                self.update_drafts_list()
                self.log_message("Draft saved.")
            else:
                self.log_message("Draft already exists.")

    def delete_draft(self, index):
        if 0 <= index < len(self.drafts):
            self.drafts.pop(index)
            self.save_drafts_local()
            self.update_drafts_list()
            self.log_message("Draft deleted.")

    def load_draft_text(self, text):
        self.message_box.delete("1.0", "end")
        self.message_box.insert("1.0", text)

    def start_broadcast(self):
        message = self.message_box.get("1.0", "end-1c").strip()
        if not message:
            self.log_message("Error: Message is empty.")
            return

        target_ids = [gid for gid, var in self.group_vars.items() if var.get()]
        if not target_ids:
            self.log_message("Error: No groups selected.")
            return

        self.log_message(f"Starting broadcast to {len(target_ids)} groups...")
        self.start_btn.configure(state="disabled")
        
        # Run broadcast in a separate thread so GUI doesn't freeze during sleeps
        threading.Thread(target=self._broadcast_task, args=(target_ids, message), daemon=True).start()

    def _broadcast_task(self, target_ids, message):
        total = len(target_ids)
        is_unique = self.unique_mode_var.get()

        for i, gid in enumerate(target_ids):
            try:
                # Resolve group name for logging
                group_data = next((g for g in self.groups if g['id'] == gid), None)
                group_name = group_data['title'] if group_data else str(gid)
                slowmode = group_data.get('slowmode', 0) if group_data else 0
                
                # Prepare message (Spintax)
                msg_to_send = parse_spintax(message) if is_unique else message

                # Send
                future = self.manager.send_message(gid, msg_to_send)
                # Wait for result synchronously in this worker thread
                while not future.done():
                    time.sleep(0.1)
                future.result() # Raise exception if any

                self.log_message(f"Sent to: {group_name}")
                
                # Update progress
                progress = (i + 1) / total
                self.progress_bar.set(progress)

                # Anti-spam delay
                if i < total - 1:
                    # Delay is max(random_delay, group_slowmode)
                    rand_delay = random.uniform(5, 10)
                    delay = max(rand_delay, slowmode)
                    
                    if slowmode > rand_delay:
                        self.log_message(f"Slow mode active! Waiting {delay:.1f}s...")
                    else:
                        self.log_message(f"Random delay: Waiting {delay:.1f}s...")
                    
                    time.sleep(delay)

            except Exception as e:
                self.log_message(f"Failed to send to {gid}: {e}")

        self.log_message("Broadcast complete!")
        self.start_btn.configure(state="normal")
        self.progress_bar.set(0)

if __name__ == "__main__":
    app = App()
    app.mainloop()

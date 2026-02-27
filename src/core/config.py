import os
import sys
import json
import logging
from dotenv import load_dotenv

# --- Path Logic ---
if hasattr(sys, '_MEIPASS'):
    # In bundle, assets are in the root of _MEIPASS
    BUNDLE_DIR = sys._MEIPASS
    DATA_DIR = os.path.dirname(sys.executable)
    APP_LOGO_PATH = os.path.join(BUNDLE_DIR, "app_logo_image.png")
    ENV_PATH = os.path.join(BUNDLE_DIR, ".env")
else:
    # In source, assets are in the project root
    # src/core/config.py -> 2 levels up to root
    BUNDLE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATA_DIR = BUNDLE_DIR
    APP_LOGO_PATH = os.path.join(BUNDLE_DIR, "app_logo_image.png")
    ENV_PATH = os.path.join(BUNDLE_DIR, ".env")

# Persistence
ERROR_LOG_FILE = os.path.join(DATA_DIR, "error_log.txt")
SESSIONS_DIR   = os.path.join(DATA_DIR, "sessions")
GROUPS_FILE    = os.path.join(DATA_DIR, "groups.json")
DRAFTS_FILE    = os.path.join(DATA_DIR, "drafts.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")
SETTINGS_FILE  = os.path.join(DATA_DIR, "settings.json")

# Ensure directories exist
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Load Environment
load_dotenv(ENV_PATH)

class Config:
    def __init__(self):
        self.settings = self._load_settings()
        self.api_id = os.getenv("TG_API_ID") or self.settings.get("api_id")
        self.api_hash = os.getenv("TG_API_HASH") or self.settings.get("api_hash")
        
        try:
            if self.api_id:
                self.api_id = int(self.api_id)
        except (ValueError, TypeError):
            self.api_id = None

    def _load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_settings(self, updates: dict):
        self.settings.update(updates)
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f)
        except Exception as e:
            logging.error(f"Failed to save settings: {e}")

    def get_last_phone(self):
        return self.settings.get("last_phone")

    def set_last_phone(self, phone):
        self.save_settings({"last_phone": phone})

# Win11 Design Tokens
WIN11 = {
    "bg_base":        "#1C1C1C",
    "bg_surface":     "#242424",
    "bg_overlay":     "#2C2C2C",
    "bg_input":       "#323232",
    "bg_hover":       "#3A3A3A",
    "accent":         "#0078D4",
    "accent_hover":   "#1383D8",
    "accent_dim":     "#005A9E",
    "success":        "#107C10",
    "success_hover":  "#0D6A0D",
    "warning":        "#FF8C00",
    "danger":         "#C42B1C",
    "danger_hover":   "#A3261A",
    "text_primary":   "#FFFFFF",
    "text_secondary": "#ABABAB",
    "text_disabled":  "#686868",
    "border":         "#3D3D3D",
    "border_focus":   "#0078D4",
    "sidebar_bg":     "#202020",
    "sidebar_active": "#2C2C2C",
}

FONT_FAMILY = "Segoe UI"

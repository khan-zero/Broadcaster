import os
import asyncio
import threading
import logging
import re
import json
from telethon import TelegramClient, errors
from .config import SESSIONS_DIR, BLACKLIST_FILE

class AsyncLoopThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self._stop_event = threading.Event()

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def run_coroutine(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)

class TelegramManager:
    def __init__(self, config, log_callback):
        self.config = config
        self.log = log_callback
        self.loop_thread = AsyncLoopThread()
        self.loop_thread.start()
        self.client = None
        self.phone = None

    def connect(self, phone=None):
        if phone:
            self.phone = phone
            session_path = os.path.join(SESSIONS_DIR, f"{phone}")
        else:
            session_path = os.path.join(SESSIONS_DIR, "default")

        self.client = TelegramClient(
            session_path, 
            self.config.api_id, 
            self.config.api_hash, 
            loop=self.loop_thread.loop
        )
        return self.loop_thread.run_coroutine(self.client.connect())

    def is_user_authorized(self):
        return self.loop_thread.run_coroutine(self.client.is_user_authorized())

    def send_code_request(self, phone):
        clean_phone = '+' + re.sub(r'\D', '', phone)
        self.phone = clean_phone
        return self.loop_thread.run_coroutine(self._send_code_wrapper(clean_phone))

    async def _send_code_wrapper(self, phone):
        try:
            return await self.client.send_code_request(phone)
        except Exception as e:
            logging.error(f"SendCode Error: {e}")
            raise

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
        except Exception as e:
            logging.error(f"Sign-in failed: {e}")
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
            except Exception as e:
                logging.error(f"Failed to load blacklist: {e}")

        try:
            async for dialog in self.client.iter_dialogs():
                try:
                    if not (dialog.is_group or dialog.is_channel):
                        continue
                    
                    is_megagroup = False
                    if dialog.is_channel:
                        if not getattr(dialog.entity, 'megagroup', False):
                            continue
                        is_megagroup = True

                    entity = dialog.entity
                    if getattr(entity, 'restricted', False) or getattr(entity, 'left', False):
                        continue

                    groups.append({
                        "id": dialog.id,
                        "title": dialog.name,
                        "type": "megagroup" if is_megagroup else "group",
                        "slowmode": getattr(entity, 'slowmode_seconds', 0) or 0,
                        "slowmode_until": 0,
                        "is_blacklisted": dialog.id in blacklist
                    })
                except Exception as e:
                    logging.error(f"Error processing dialog {dialog.id}: {e}")
        except Exception as e:
            logging.error(f"Error iterating dialogs: {e}")
            raise
        
        return groups

    def send_message(self, entity_id, message):
        return self.loop_thread.run_coroutine(self.client.send_message(entity_id, message))

    def disconnect(self):
        if self.client:
            return self.loop_thread.run_coroutine(self.client.disconnect())

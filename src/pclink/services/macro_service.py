# src/pclink/services/macro_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from ..core import constants
from .app_service import app_service
from .file_service import file_service
from .input_service import input_service
from .media_service import media_service
from .system_service import system_service
from .utility_service import utility_service

log = logging.getLogger(__name__)


class MacroService:
    """Orchestrates multi-step actions across various PCLink services."""

    def __init__(self):
        self._notification_handler: Optional[Callable[[str, str], None]] = None
        self.macros_file = constants.MACROS_FILE
        self._macros: Dict[str, Dict[str, Any]] = {}
        self._load_macros()

    def _load_macros(self):
        """Load macros from the JSON storage file."""
        if not self.macros_file.exists():
            log.info("No macros file found. Starting with an empty list.")
            self._macros = {}
            return

        try:
            with self.macros_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Migration: Convert old list-based format to dict-based (indexed by ID)
                    self._macros = {m.get("id", str(uuid.uuid4())): m for m in data}
                    self._save_macros()  # Standardize format
                else:
                    self._macros = data
            log.info(f"Loaded {len(self._macros)} macros from {self.macros_file}")
        except Exception as e:
            log.error(f"Failed to load macros: {e}")
            self._macros = {}

    def _save_macros(self):
        """Persist current macros to the JSON file."""
        try:
            self.macros_file.parent.mkdir(parents=True, exist_ok=True)
            with self.macros_file.open("w", encoding="utf-8") as f:
                json.dump(self._macros, f, indent=4)
        except Exception as e:
            log.error(f"Failed to save macros: {e}")

    def get_macros(self) -> List[Dict[str, Any]]:
        """Return all stored macros as a list."""
        return list(self._macros.values())

    def save_macro(self, macro_data: Dict[str, Any]) -> Dict[str, Any]:
        """Save or update a macro."""
        m_id = macro_data.get("id")
        if not m_id:
            m_id = str(uuid.uuid4())
            macro_data["id"] = m_id

        self._macros[m_id] = macro_data
        self._save_macros()
        return macro_data

    def delete_macro(self, macro_id: str) -> bool:
        """Remove a macro by ID."""
        if macro_id in self._macros:
            del self._macros[macro_id]
            self._save_macros()
            return True
        return False

    def set_notification_handler(self, handler: Callable[[str, str], None]):
        self._notification_handler = handler

    async def execute_macro(self, name: str, actions: List[Dict[str, Any]]):
        log.info(f"Executing macro: {name} ({len(actions)} steps)")

        for i, step in enumerate(actions):
            action_type = step.get("type")
            payload = step.get("payload", {})
            log.debug(f"Step {i + 1}: {action_type}")

            try:
                await self._execute_step(action_type, payload)
            except Exception as e:
                log.error(f"Macro '{name}' failed at step {i + 1} ({action_type}): {e}")
                raise

    async def _execute_step(self, action_type: str, payload: Dict[str, Any]):
        if action_type == "launch_app":
            cmd = payload.get("command")
            if not cmd:
                raise ValueError("Missing command")
            await app_service.launch(cmd)

        elif action_type == "power":
            cmd = payload.get("command")
            if not cmd:
                raise ValueError("Missing power command")
            await system_service.power_command(cmd)

        elif action_type == "media":
            action = payload.get("action")
            if not action:
                raise ValueError("Missing media action")
            await media_service.media_command(action)

        elif action_type == "volume":
            lvl = payload.get("level")
            if lvl is None:
                raise ValueError("Missing volume level")
            await system_service.set_volume(int(lvl))

        elif action_type == "delay":
            ms = payload.get("duration_ms")
            if not ms:
                raise ValueError("Missing duration")
            await asyncio.sleep(int(ms) / 1000.0)

        elif action_type == "command":
            cmd = payload.get("command")
            if not cmd:
                raise ValueError("Missing shell command")
            await utility_service.run_command_detached(cmd)

        elif action_type == "input_text":
            text = payload.get("text")
            if text is None:
                raise ValueError("Missing text")
            input_service.keyboard_type(text)

        elif action_type == "input_keys":
            key = payload.get("custom_key") or payload.get("key")
            if not key:
                raise ValueError("Missing key")
            modifiers = payload.get("modifiers", [])
            input_service.keyboard_press_key(key, modifiers)

        elif action_type == "clipboard":
            text = payload.get("text")
            if text is None:
                raise ValueError("Missing clipboard text")
            await utility_service.set_clipboard(text)

        elif action_type == "notification":
            title = payload.get("title", "PCLink Macro")
            msg = payload.get("message", "")
            if self._notification_handler:
                self._notification_handler(title, msg)
            else:
                log.warning("Notification requested but no handler registered")

        elif action_type == "file":
            path = payload.get("path")
            if not path:
                raise ValueError("Missing file path")
            # We don't have 'open' in file_service yet, but we can reuse the logic
            import os
            import subprocess
            import sys

            p = file_service.validate_path(path)
            if sys.platform == "win32":
                os.startfile(p)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(p)])
            else:
                subprocess.run(["xdg-open", str(p)])

        else:
            raise ValueError(f"Unknown action type: {action_type}")


# Global instance
macro_service = MacroService()

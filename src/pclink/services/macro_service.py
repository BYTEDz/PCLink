# src/pclink/services/macro_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable

from .system_service import system_service
from .media_service import media_service
from .input_service import input_service
from .app_service import app_service
from .utility_service import utility_service
from .file_service import file_service

log = logging.getLogger(__name__)

class MacroService:
    """Orchestrates multi-step actions across various PCLink services."""

    def __init__(self):
        self._notification_handler: Optional[Callable[[str, str], None]] = None

    def set_notification_handler(self, handler: Callable[[str, str], None]):
        self._notification_handler = handler

    async def execute_macro(self, name: str, actions: List[Dict[str, Any]]):
        log.info(f"Executing macro: {name} ({len(actions)} steps)")
        
        for i, step in enumerate(actions):
            action_type = step.get("type")
            payload = step.get("payload", {})
            log.debug(f"Step {i+1}: {action_type}")
            
            try:
                await self._execute_step(action_type, payload)
            except Exception as e:
                log.error(f"Macro '{name}' failed at step {i+1} ({action_type}): {e}")
                raise

    async def _execute_step(self, action_type: str, payload: Dict[str, Any]):
        if action_type == "launch_app":
            cmd = payload.get("command")
            if not cmd: raise ValueError("Missing command")
            await app_service.launch(cmd)
            
        elif action_type == "power":
            cmd = payload.get("command")
            if not cmd: raise ValueError("Missing power command")
            await system_service.power_command(cmd)
            
        elif action_type == "media":
            action = payload.get("action")
            if not action: raise ValueError("Missing media action")
            await media_service.media_command(action)
            
        elif action_type == "volume":
            lvl = payload.get("level")
            if lvl is None: raise ValueError("Missing volume level")
            await system_service.set_volume(int(lvl))
            
        elif action_type == "delay":
            ms = payload.get("duration_ms")
            if not ms: raise ValueError("Missing duration")
            await asyncio.sleep(int(ms) / 1000.0)
            
        elif action_type == "command":
            cmd = payload.get("command")
            if not cmd: raise ValueError("Missing shell command")
            await utility_service.run_command_detached(cmd)
            
        elif action_type == "input_text":
            text = payload.get("text")
            if text is None: raise ValueError("Missing text")
            input_service.keyboard_type(text)
            
        elif action_type == "input_keys":
            key = payload.get("key")
            if not key: raise ValueError("Missing key")
            modifiers = payload.get("modifiers", [])
            input_service.keyboard_press_key(key, modifiers)
            
        elif action_type == "clipboard":
            text = payload.get("text")
            if text is None: raise ValueError("Missing clipboard text")
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
            if not path: raise ValueError("Missing file path")
            # We don't have 'open' in file_service yet, but we can reuse the logic
            import sys, subprocess, os
            p = file_service.validate_path(path)
            if sys.platform == "win32": os.startfile(p)
            elif sys.platform == "darwin": subprocess.run(["open", str(p)])
            else: subprocess.run(["xdg-open", str(p)])
            
        else:
            raise ValueError(f"Unknown action type: {action_type}")

# Global instance
macro_service = MacroService()

# src/pclink/services/input_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Any, Dict, List, Optional

try:
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key
    from pynput.mouse import Button
    from pynput.mouse import Controller as MouseController
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

log = logging.getLogger(__name__)

class InputService:
    """Logic for remote input control: mouse and keyboard."""
    
    def __init__(self):
        if PYNPUT_AVAILABLE:
            self.mouse = MouseController()
            self.keyboard = KeyboardController()
            self.button_map = {"left": Button.left, "right": Button.right, "middle": Button.middle}
            self.key_map = {
                "enter": Key.enter, "esc": Key.esc, "shift": Key.shift, "ctrl": Key.ctrl,
                "alt": Key.alt, "cmd": Key.cmd, "win": Key.cmd, "backspace": Key.backspace,
                "delete": Key.delete, "tab": Key.tab, "space": Key.space,
                "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
            }
        else:
            self.mouse = None
            self.keyboard = None

    def mouse_move(self, dx: int, dy: int):
        if self.mouse: self.mouse.move(dx, dy)

    def mouse_click(self, button: str = "left", clicks: int = 1):
        if self.mouse:
            btn = self.button_map.get(button, Button.left)
            self.mouse.click(btn, clicks)

    def mouse_scroll(self, dx: int, dy: int):
        if self.mouse: self.mouse.scroll(dx, dy)

    def keyboard_type(self, text: str):
        if self.keyboard: self.keyboard.type(text)

    def keyboard_press_key(self, key_str: str, modifiers: List[str] = None):
        if not self.keyboard: return
        try:
            mods = [self.key_map.get(m.lower(), m) for m in (modifiers or [])]
            key = self.key_map.get(key_str.lower(), key_str)
            
            for m in mods: self.keyboard.press(m)
            self.keyboard.press(key)
            self.keyboard.release(key)
            for m in reversed(mods): self.keyboard.release(m)
        except Exception as e:
            log.error(f"Keyboard command failed: {e}")

# Global instance
input_service = InputService()

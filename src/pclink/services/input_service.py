# src/pclink/services/input_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import List

from ..core.wayland_utils import is_wayland
from .linux_evdev_service import LinuxEvdevService

try:
    from pynput.mouse import Button

    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

log = logging.getLogger(__name__)


class InputService:
    """Logic for remote input control: mouse and keyboard."""

    def __init__(self):
        self.use_evdev = False
        self.evdev = None
        self.mouse = None
        self.keyboard = None
        self.button_map = {}
        self.key_map = {}

        # Prefer evdev on Linux + Wayland
        if is_wayland():
            self.evdev = LinuxEvdevService()
            if self.evdev.ui:
                self.use_evdev = True
                log.info("InputService: Using evdev (Wayland mode)")

        if not self.use_evdev and PYNPUT_AVAILABLE:
            log.info("InputService: Using pynput (Standard OS mode)")
            from pynput.keyboard import Controller as KeyboardController
            from pynput.keyboard import Key
            from pynput.mouse import Button
            from pynput.mouse import Controller as MouseController

            self.mouse = MouseController()
            self.keyboard = KeyboardController()
            self.button_map = {
                "left": Button.left,
                "right": Button.right,
                "middle": Button.middle,
            }
            self.key_map = {
                "enter": Key.enter,
                "esc": Key.esc,
                "shift": Key.shift,
                "ctrl": Key.ctrl,
                "alt": Key.alt,
                "cmd": Key.cmd,
                "win": Key.cmd,
                "meta": Key.cmd,
                "super": Key.cmd,
                "backspace": Key.backspace,
                "delete": Key.delete,
                "tab": Key.tab,
                "space": Key.space,
                "up": Key.up,
                "down": Key.down,
                "left": Key.left,
                "right": Key.right,
            }

    def is_available(self) -> bool:
        """Check if any input backend is active."""
        return self.use_evdev or (self.mouse is not None and self.keyboard is not None)

    def mouse_move(self, dx: int, dy: int):
        """Dispatches mouse movement deltas directly to the active hardware/virtual backend."""
        if not dx and not dy:
            return

        if self.use_evdev:
            self.evdev.move_relative(dx, dy)
        elif self.mouse:
            self.mouse.move(dx, dy)

    def mouse_click(self, button: str = "left", clicks: int = 1):
        if self.use_evdev:
            self.evdev.click(button, clicks)
        elif self.mouse:
            btn = self.button_map.get(button, Button.left)
            self.mouse.click(btn, clicks)

    def mouse_scroll(self, dx: int, dy: int):
        if not dx and not dy:
            return

        if self.use_evdev:
            self.evdev.scroll(dx, dy)
        elif self.mouse:
            self.mouse.scroll(dx, dy)

    def keyboard_type(self, text: str):
        log.info(
            f"[INPUT_SERVICE] keyboard_type: text='{text}', use_evdev={self.use_evdev}"
        )
        if self.use_evdev:
            self.evdev.type_text(text)
        elif self.keyboard:
            try:
                self.keyboard.type(text)
            except Exception as e:
                log.warning(
                    f"[INPUT_SERVICE] pynput type failed, attempting clipboard paste: {e}"
                )
                try:
                    import pyperclip
                    from pynput.keyboard import Key

                    pyperclip.copy(text)
                    self.keyboard.press(Key.ctrl)
                    self.keyboard.press("v")
                    self.keyboard.release("v")
                    self.keyboard.release(Key.ctrl)
                except Exception as ex:
                    log.error(f"[INPUT_SERVICE] Clipboard paste fallback failed: {ex}")

    def keyboard_press_key(self, key_str: str, modifiers: List[str] = None):
        log.info(
            f"[INPUT_SERVICE] keyboard_press_key: key='{key_str}', modifiers={modifiers}, use_evdev={self.use_evdev}"
        )
        if self.use_evdev:
            self.evdev.press_key(key_str, modifiers)
        elif self.keyboard:
            try:
                mods = [self.key_map.get(m.lower(), m) for m in (modifiers or [])]
                key = self.key_map.get(key_str.lower(), key_str)

                for m in mods:
                    self.keyboard.press(m)
                self.keyboard.press(key)
                self.keyboard.release(key)
                for m in reversed(mods):
                    self.keyboard.release(m)
            except Exception as e:
                log.error(f"Keyboard command failed: {e}")


# Global instance
input_service = InputService()

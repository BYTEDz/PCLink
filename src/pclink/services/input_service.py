# src/pclink/services/input_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import sys
from typing import List, Optional

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

        # Enable native kernel uinput device across all Linux sessions (Wayland and X11)
        if sys.platform.startswith("linux"):
            self.evdev = LinuxEvdevService()
            if self.evdev.ui:
                self.use_evdev = True
                log.info(
                    "InputService: Using Linux kernel evdev (uinput virtual hardware mode)"
                )

        if not self.use_evdev and PYNPUT_AVAILABLE:
            log.info("InputService: Using pynput (Standard OS fallback mode)")
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
            if hasattr(Button, "x1"):
                self.button_map["x1"] = Button.x1
                self.button_map["side"] = Button.x1
                self.button_map["back"] = Button.x1
            if hasattr(Button, "x2"):
                self.button_map["x2"] = Button.x2
                self.button_map["extra"] = Button.x2
                self.button_map["forward"] = Button.x2

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
                "home": Key.home,
                "end": Key.end,
                "pageup": Key.page_up,
                "pagedown": Key.page_down,
                "caps_lock": Key.caps_lock,
                "f1": Key.f1,
                "f2": Key.f2,
                "f3": Key.f3,
                "f4": Key.f4,
                "f5": Key.f5,
                "f6": Key.f6,
                "f7": Key.f7,
                "f8": Key.f8,
                "f9": Key.f9,
                "f10": Key.f10,
                "f11": Key.f11,
                "f12": Key.f12,
            }

    def is_available(self) -> bool:
        """Check if any input backend is active."""
        return self.use_evdev or (self.mouse is not None and self.keyboard is not None)

    def raw_key(self, scan_code: int, is_down: bool):
        """Passes a raw hardware key scancode directly into the kernel uinput bus."""
        if self.use_evdev and self.evdev:
            self.evdev.raw_key(scan_code, is_down)
        elif self.keyboard:
            try:
                from pynput.keyboard import KeyCode

                vk = KeyCode.from_vk(scan_code) if hasattr(KeyCode, "from_vk") else None
                if vk:
                    if is_down:
                        self.keyboard.press(vk)
                    else:
                        self.keyboard.release(vk)
            except Exception as e:
                log.debug(f"raw_key fallback failed for {scan_code}: {e}")

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

    def mouse_down(self, button: str = "left"):
        """Holds mouse button down for dragging or text selection."""
        if self.use_evdev:
            self.evdev.mouse_down(button)
        elif self.mouse:
            btn = self.button_map.get(button, Button.left)
            self.mouse.press(btn)

    def mouse_up(self, button: str = "left"):
        """Releases held mouse button."""
        if self.use_evdev:
            self.evdev.mouse_up(button)
        elif self.mouse:
            btn = self.button_map.get(button, Button.left)
            self.mouse.release(btn)

    def mouse_scroll(self, dx: int, dy: int):
        if not dx and not dy:
            return

        if self.use_evdev:
            self.evdev.scroll(dx, dy)
        elif self.mouse:
            self.mouse.scroll(dx, dy)

    def keyboard_type(self, text: str):
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

    def keyboard_press_key(self, key_str: str, modifiers: Optional[List[str]] = None):
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

    def key_down(self, key_str: str, modifiers: Optional[List[str]] = None):
        """Holds key down for hardware keyboard passthrough."""
        if self.use_evdev:
            self.evdev.key_down(key_str, modifiers)
        elif self.keyboard:
            try:
                mods = [self.key_map.get(m.lower(), m) for m in (modifiers or [])]
                key = self.key_map.get(key_str.lower(), key_str)
                for m in mods:
                    self.keyboard.press(m)
                self.keyboard.press(key)
            except Exception as e:
                log.error(f"Key down failed: {e}")

    def key_up(self, key_str: str, modifiers: Optional[List[str]] = None):
        """Releases held key."""
        if self.use_evdev:
            self.evdev.key_up(key_str, modifiers)
        elif self.keyboard:
            try:
                mods = [self.key_map.get(m.lower(), m) for m in (modifiers or [])]
                key = self.key_map.get(key_str.lower(), key_str)
                self.keyboard.release(key)
                for m in reversed(mods):
                    self.keyboard.release(m)
            except Exception as e:
                log.error(f"Key up failed: {e}")


# Global instance
input_service = InputService()

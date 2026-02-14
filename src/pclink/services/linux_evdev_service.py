# src/pclink/services/linux_evdev_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import time
from typing import List, Optional

try:
    from evdev import UInput, ecodes, AbsInfo
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False

log = logging.getLogger(__name__)

class LinuxEvdevService:
    """
    Low-level Linux input service using uinput/evdev.
    Bypasses Wayland security by creating virtual hardware devices.
    """

    def __init__(self):
        self.ui = None
        if not EVDEV_AVAILABLE:
            log.warning("evdev not installed. Wayland input will not work.")
            return

        try:
            # Define human interface devices (Keyboard + Mouse)
            capabilities = {
                ecodes.EV_KEY: [
                    # Keyboard keys
                    ecodes.KEY_ESC, ecodes.KEY_1, ecodes.KEY_2, ecodes.KEY_3, ecodes.KEY_4, 
                    ecodes.KEY_5, ecodes.KEY_6, ecodes.KEY_7, ecodes.KEY_8, ecodes.KEY_9, 
                    ecodes.KEY_0, ecodes.KEY_MINUS, ecodes.KEY_EQUAL, ecodes.KEY_BACKSPACE, 
                    ecodes.KEY_TAB, ecodes.KEY_Q, ecodes.KEY_W, ecodes.KEY_E, ecodes.KEY_R, 
                    ecodes.KEY_T, ecodes.KEY_Y, ecodes.KEY_U, ecodes.KEY_I, ecodes.KEY_O, 
                    ecodes.KEY_P, ecodes.KEY_LEFTBRACE, ecodes.KEY_RIGHTBRACE, ecodes.KEY_ENTER, 
                    ecodes.KEY_LEFTCTRL, ecodes.KEY_A, ecodes.KEY_S, ecodes.KEY_D, ecodes.KEY_F, 
                    ecodes.KEY_G, ecodes.KEY_H, ecodes.KEY_J, ecodes.KEY_K, ecodes.KEY_L, 
                    ecodes.KEY_SEMICOLON, ecodes.KEY_APOSTROPHE, ecodes.KEY_GRAVE, ecodes.KEY_LEFTSHIFT, 
                    ecodes.KEY_BACKSLASH, ecodes.KEY_Z, ecodes.KEY_X, ecodes.KEY_C, ecodes.KEY_V, 
                    ecodes.KEY_B, ecodes.KEY_N, ecodes.KEY_M, ecodes.KEY_COMMA, ecodes.KEY_DOT, 
                    ecodes.KEY_SLASH, ecodes.KEY_RIGHTSHIFT, ecodes.KEY_KPASTERISK, ecodes.KEY_LEFTALT, 
                    ecodes.KEY_SPACE, ecodes.KEY_CAPSLOCK, ecodes.KEY_F1, ecodes.KEY_F2, ecodes.KEY_F3, 
                    ecodes.KEY_F4, ecodes.KEY_F5, ecodes.KEY_F6, ecodes.KEY_F7, ecodes.KEY_F8, 
                    ecodes.KEY_F9, ecodes.KEY_F10, ecodes.KEY_NUMLOCK, ecodes.KEY_SCROLLLOCK,
                    ecodes.KEY_LEFT, ecodes.KEY_RIGHT, ecodes.KEY_UP, ecodes.KEY_DOWN,
                    ecodes.KEY_DELETE, ecodes.KEY_HOME, ecodes.KEY_END, ecodes.KEY_PAGEUP, ecodes.KEY_PAGEDOWN,
                    # Mouse buttons
                    ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE
                ],
                ecodes.EV_REL: [
                    ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL
                ]
            }
            
            self.ui = UInput(capabilities, name="PCLink Virtual Input")
            log.info("Successfully created PCLink Virtual Input device via uinput.")
            
            # Map standard strings to ecodes
            self.key_map = {
                "enter": ecodes.KEY_ENTER, "esc": ecodes.KEY_ESC, "shift": ecodes.KEY_LEFTSHIFT,
                "ctrl": ecodes.KEY_LEFTCTRL, "alt": ecodes.KEY_LEFTALT, "cmd": ecodes.KEY_LEFTMETA,
                "win": ecodes.KEY_LEFTMETA, "backspace": ecodes.KEY_BACKSPACE, "delete": ecodes.KEY_DELETE,
                "tab": ecodes.KEY_TAB, "space": ecodes.KEY_SPACE, "up": ecodes.KEY_UP,
                "down": ecodes.KEY_DOWN, "left": ecodes.KEY_LEFT, "right": ecodes.KEY_RIGHT,
            }
            
            self.btn_map = {
                "left": ecodes.BTN_LEFT, "right": ecodes.BTN_RIGHT, "middle": ecodes.BTN_MIDDLE
            }

        except Exception as e:
            log.error(f"Failed to initialize uinput device: {e}. Check /dev/uinput permissions.")
            self.ui = None

    def move_relative(self, dx: int, dy: int):
        if self.ui:
            # Round floats to nearest int as uinput expects Absolute/Relative integers
            self.ui.write(ecodes.EV_REL, ecodes.REL_X, int(round(dx)))
            self.ui.write(ecodes.EV_REL, ecodes.REL_Y, int(round(dy)))
            self.ui.syn()

    def click(self, button: str = "left", clicks: int = 1):
        if not self.ui: return
        btn = self.btn_map.get(button.lower(), ecodes.BTN_LEFT)
        for _ in range(clicks):
            self.ui.write(ecodes.EV_KEY, btn, 1) # Press
            self.ui.syn()
            time.sleep(0.01)
            self.ui.write(ecodes.EV_KEY, btn, 0) # Release
            self.ui.syn()
            if clicks > 1: time.sleep(0.05)

    def scroll(self, dx: int, dy: int):
        if not self.ui: return
        if dy != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_WHEEL, int(round(dy)))
        if dx != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_HWHEEL, int(round(dx)))
        self.ui.syn()

    def type_text(self, text: str):
        # Simplistic mapping for common characters (mostly for quick commands)
        # Full keyboard mapping is complex; usually we use scancodes or keysyms.
        for char in text:
            code = self._char_to_ecode(char)
            if code:
                self.ui.write(ecodes.EV_KEY, code, 1)
                self.ui.syn()
                self.ui.write(ecodes.EV_KEY, code, 0)
                self.ui.syn()

    def press_key(self, key_str: str, modifiers: List[str] = None):
        if not self.ui: return
        try:
            mods = [self.key_map.get(m.lower(), None) for m in (modifiers or [])]
            mods = [m for m in mods if m is not None]
            
            main_key = self.key_map.get(key_str.lower(), None)
            if main_key is None:
                # Fallback to single char mapping if it's a letter
                main_key = self._char_to_ecode(key_str)

            if main_key:
                for m in mods: self.ui.write(ecodes.EV_KEY, m, 1)
                self.ui.write(ecodes.EV_KEY, main_key, 1)
                self.ui.syn()
                
                self.ui.write(ecodes.EV_KEY, main_key, 0)
                for m in reversed(mods): self.ui.write(ecodes.EV_KEY, m, 0)
                self.ui.syn()
        except Exception as e:
            log.error(f"evdev press_key failed: {e}")

    def _char_to_ecode(self, char: str):
        # basic ASCII to ecode bridge
        c = char.lower()
        mapping = {
            'a': ecodes.KEY_A, 'b': ecodes.KEY_B, 'c': ecodes.KEY_C, 'd': ecodes.KEY_D,
            'e': ecodes.KEY_E, 'f': ecodes.KEY_F, 'g': ecodes.KEY_G, 'h': ecodes.KEY_H,
            'i': ecodes.KEY_I, 'j': ecodes.KEY_J, 'k': ecodes.KEY_K, 'l': ecodes.KEY_L,
            'm': ecodes.KEY_M, 'n': ecodes.KEY_N, 'o': ecodes.KEY_O, 'p': ecodes.KEY_P,
            'q': ecodes.KEY_Q, 'r': ecodes.KEY_R, 's': ecodes.KEY_S, 't': ecodes.KEY_T,
            'u': ecodes.KEY_U, 'v': ecodes.KEY_V, 'w': ecodes.KEY_W, 'x': ecodes.KEY_X,
            'y': ecodes.KEY_Y, 'z': ecodes.KEY_Z, '1': ecodes.KEY_1, '2': ecodes.KEY_2,
            '.': ecodes.KEY_DOT, '/': ecodes.KEY_SLASH, '-': ecodes.KEY_MINUS, ' ': ecodes.KEY_SPACE
        }
        return mapping.get(c)

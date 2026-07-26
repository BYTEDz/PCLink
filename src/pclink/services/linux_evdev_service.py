# src/pclink/services/linux_evdev_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import ctypes
import ctypes.util
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from evdev import UInput, ecodes

    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False

from ..core.config import config_manager

log = logging.getLogger(__name__)


def _build_dynamic_xkb_map(
    layout_name: str, variant: str = ""
) -> Dict[str, Tuple[int, bool, bool]]:
    """
    Dynamically queries libxkbcommon to build a map from unicode characters
    to (evdev_keycode, need_shift, need_altgr) for ANY active Linux keyboard layout.
    """
    lib_path = ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0"
    try:
        xkb = ctypes.CDLL(lib_path)
    except Exception as e:
        log.warning(f"[EVDEV_XKB] Could not load libxkbcommon: {e}")
        return {}

    try:
        xkb.xkb_context_new.restype = ctypes.c_void_p
        xkb.xkb_context_new.argtypes = [ctypes.c_int]

        xkb.xkb_context_unref.restype = None
        xkb.xkb_context_unref.argtypes = [ctypes.c_void_p]

        class XkbRuleNames(ctypes.Structure):
            _fields_ = [
                ("rules", ctypes.c_char_p),
                ("model", ctypes.c_char_p),
                ("layout", ctypes.c_char_p),
                ("variant", ctypes.c_char_p),
                ("options", ctypes.c_char_p),
            ]

        xkb.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        xkb.xkb_keymap_new_from_names.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(XkbRuleNames),
            ctypes.c_int,
        ]

        xkb.xkb_keymap_unref.restype = None
        xkb.xkb_keymap_unref.argtypes = [ctypes.c_void_p]

        xkb.xkb_keymap_key_get_syms_by_level.restype = ctypes.c_int
        xkb.xkb_keymap_key_get_syms_by_level.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        ]

        xkb.xkb_keysym_to_utf8.restype = ctypes.c_int
        xkb.xkb_keysym_to_utf8.argtypes = [
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]

        ctx = xkb.xkb_context_new(0)
        if not ctx:
            return {}

        clean_layout = layout_name.lower().strip()
        if clean_layout == "azerty":
            clean_layout = "fr"
        elif clean_layout == "qwerty":
            clean_layout = "us"

        rules = XkbRuleNames(
            rules=b"evdev",
            model=b"pc105",
            layout=clean_layout.encode("utf-8"),
            variant=variant.encode("utf-8") if variant else None,
            options=None,
        )

        keymap = xkb.xkb_keymap_new_from_names(ctx, ctypes.byref(rules), 0)
        if not keymap and variant:
            rules.variant = None
            keymap = xkb.xkb_keymap_new_from_names(ctx, ctypes.byref(rules), 0)

        if not keymap:
            xkb.xkb_context_unref(ctx)
            return {}

        char_map: Dict[str, Tuple[int, bool, bool]] = {}
        buf = ctypes.create_string_buffer(32)

        # Scanner levels: (level_idx, need_shift, need_altgr)
        levels = [
            (0, False, False),  # Normal
            (1, True, False),  # Shift
            (2, False, True),  # AltGr
            (3, True, True),  # Shift + AltGr
        ]

        syms_ptr = ctypes.POINTER(ctypes.c_uint32)()

        # Scan XKB keycodes (8 to 255 -> evdev keycodes 0 to 247)
        for evdev_code in range(1, 248):
            xkb_code = evdev_code + 8
            for level, shift, altgr in levels:
                num_syms = xkb.xkb_keymap_key_get_syms_by_level(
                    keymap, xkb_code, 0, level, ctypes.byref(syms_ptr)
                )
                if num_syms > 0 and syms_ptr:
                    for i in range(num_syms):
                        sym = syms_ptr[i]
                        res_len = xkb.xkb_keysym_to_utf8(sym, buf, 32)
                        if res_len > 1:
                            char_val = buf.value.decode("utf-8", errors="ignore")
                            if char_val and char_val not in char_map:
                                char_map[char_val] = (evdev_code, shift, altgr)

        xkb.xkb_keymap_unref(keymap)
        xkb.xkb_context_unref(ctx)

        log.info(
            f"[EVDEV_XKB] Dynamically generated {len(char_map)} character mappings for layout '{clean_layout}'."
        )
        return char_map

    except Exception as e:
        log.error(f"[EVDEV_XKB] Error building dynamic XKB map: {e}")
        return {}


class LinuxEvdevService:
    """
    Low-level Linux input service using uinput/evdev.
    Bypasses Wayland security by creating virtual hardware devices.
    """

    def __init__(self):
        self.ui = None
        self._auto_layout = None
        self._cached_layout = None
        self._cached_xkb_map = {}

        if not EVDEV_AVAILABLE:
            log.warning("evdev not installed. Wayland input will not work.")
            return

        try:
            capabilities = {
                ecodes.EV_KEY: [
                    ecodes.KEY_ESC,
                    ecodes.KEY_1,
                    ecodes.KEY_2,
                    ecodes.KEY_3,
                    ecodes.KEY_4,
                    ecodes.KEY_5,
                    ecodes.KEY_6,
                    ecodes.KEY_7,
                    ecodes.KEY_8,
                    ecodes.KEY_9,
                    ecodes.KEY_0,
                    ecodes.KEY_MINUS,
                    ecodes.KEY_EQUAL,
                    ecodes.KEY_BACKSPACE,
                    ecodes.KEY_TAB,
                    ecodes.KEY_Q,
                    ecodes.KEY_W,
                    ecodes.KEY_E,
                    ecodes.KEY_R,
                    ecodes.KEY_T,
                    ecodes.KEY_Y,
                    ecodes.KEY_U,
                    ecodes.KEY_I,
                    ecodes.KEY_O,
                    ecodes.KEY_P,
                    ecodes.KEY_LEFTBRACE,
                    ecodes.KEY_RIGHTBRACE,
                    ecodes.KEY_ENTER,
                    ecodes.KEY_LEFTCTRL,
                    ecodes.KEY_A,
                    ecodes.KEY_S,
                    ecodes.KEY_D,
                    ecodes.KEY_F,
                    ecodes.KEY_G,
                    ecodes.KEY_H,
                    ecodes.KEY_J,
                    ecodes.KEY_K,
                    ecodes.KEY_L,
                    ecodes.KEY_SEMICOLON,
                    ecodes.KEY_APOSTROPHE,
                    ecodes.KEY_GRAVE,
                    ecodes.KEY_LEFTSHIFT,
                    ecodes.KEY_BACKSLASH,
                    ecodes.KEY_Z,
                    ecodes.KEY_X,
                    ecodes.KEY_C,
                    ecodes.KEY_V,
                    ecodes.KEY_B,
                    ecodes.KEY_N,
                    ecodes.KEY_M,
                    ecodes.KEY_COMMA,
                    ecodes.KEY_DOT,
                    ecodes.KEY_SLASH,
                    ecodes.KEY_RIGHTSHIFT,
                    ecodes.KEY_RIGHTALT,
                    ecodes.KEY_LEFTALT,
                    ecodes.KEY_SPACE,
                    ecodes.KEY_CAPSLOCK,
                    ecodes.KEY_F1,
                    ecodes.KEY_F2,
                    ecodes.KEY_F3,
                    ecodes.KEY_F4,
                    ecodes.KEY_F5,
                    ecodes.KEY_F6,
                    ecodes.KEY_F7,
                    ecodes.KEY_F8,
                    ecodes.KEY_F9,
                    ecodes.KEY_F10,
                    ecodes.KEY_NUMLOCK,
                    ecodes.KEY_SCROLLLOCK,
                    ecodes.KEY_LEFT,
                    ecodes.KEY_RIGHT,
                    ecodes.KEY_UP,
                    ecodes.KEY_DOWN,
                    ecodes.KEY_DELETE,
                    ecodes.KEY_HOME,
                    ecodes.KEY_END,
                    ecodes.KEY_PAGEUP,
                    ecodes.KEY_PAGEDOWN,
                    ecodes.KEY_LEFTMETA,
                    ecodes.KEY_RIGHTMETA,
                    ecodes.KEY_COMPOSE,
                    ecodes.KEY_MENU,
                    ecodes.BTN_LEFT,
                    ecodes.BTN_RIGHT,
                    ecodes.BTN_MIDDLE,
                ],
                ecodes.EV_REL: [
                    ecodes.REL_X,
                    ecodes.REL_Y,
                    ecodes.REL_WHEEL,
                    ecodes.REL_HWHEEL,
                ],
            }

            self.ui = UInput(capabilities, name="PCLink Virtual Input")
            log.info("Successfully created PCLink Virtual Input device via uinput.")

            self.btn_map = {
                "left": ecodes.BTN_LEFT,
                "right": ecodes.BTN_RIGHT,
                "middle": ecodes.BTN_MIDDLE,
            }

        except Exception as e:
            log.error(
                f"Failed to initialize uinput device: {e}. Check /dev/uinput permissions."
            )
            self.ui = None

    def move_relative(self, dx: int, dy: int):
        if self.ui:
            self.ui.write(ecodes.EV_REL, ecodes.REL_X, int(round(dx)))
            self.ui.write(ecodes.EV_REL, ecodes.REL_Y, int(round(dy)))
            self.ui.syn()

    def click(self, button: str = "left", clicks: int = 1):
        if not self.ui:
            return
        btn = self.btn_map.get(button.lower(), ecodes.BTN_LEFT)
        for _ in range(clicks):
            self.ui.write(ecodes.EV_KEY, btn, 1)
            self.ui.syn()
            time.sleep(0.01)
            self.ui.write(ecodes.EV_KEY, btn, 0)
            self.ui.syn()
            if clicks > 1:
                time.sleep(0.05)

    def scroll(self, dx: int, dy: int):
        if not self.ui:
            return
        if dy != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_WHEEL, int(round(dy)))
        if dx != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_HWHEEL, int(round(dx)))
        self.ui.syn()

    def _detect_system_layout(self) -> str:
        """Detect current system keyboard layout dynamically."""
        # 1. GNOME gsettings (Fedora / Ubuntu Wayland)
        try:
            import subprocess

            res = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.input-sources", "sources"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout:
                out = res.stdout.strip()
                matches = re.findall(r"\('xkb',\s*'([^']+)'\)", out)
                if matches:
                    layout = matches[0].split("+")[0]
                    log.info(f"[LAYOUT_DETECT] Detected GNOME input layout: '{layout}'")
                    return layout
        except Exception as e:
            log.debug(f"[LAYOUT_DETECT] GNOME gsettings detection failed: {e}")

        # 2. localectl status
        try:
            import subprocess

            res = subprocess.run(
                ["localectl", "status"], capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line_lower = line.lower()
                    if "x11 layout:" in line_lower or "vc keymap:" in line_lower:
                        val = (
                            line.split(":", 1)[1]
                            .strip()
                            .lower()
                            .split(",")[0]
                            .split("-")[0]
                        )
                        if val:
                            log.info(
                                f"[LAYOUT_DETECT] Detected localectl layout: '{val}'"
                            )
                            return val
        except Exception as e:
            log.debug(f"[LAYOUT_DETECT] localectl detection failed: {e}")

        # 3. Environment variables & /etc/vconsole.conf
        try:
            xkb_layout = os.environ.get("XKB_DEFAULT_LAYOUT", "").lower()
            if xkb_layout:
                return xkb_layout.split(",")[0]

            vconsole = Path("/etc/vconsole.conf")
            if vconsole.exists():
                content = vconsole.read_text().lower()
                for line in content.splitlines():
                    if line.startswith("keymap=") or line.startswith("xkblayout="):
                        val = line.split("=", 1)[1].strip("\"'").split("-")[0]
                        if val:
                            return val
        except Exception as e:
            log.debug(f"[LAYOUT_DETECT] Environment check failed: {e}")

        # 4. setxkbmap fallback
        try:
            import subprocess

            res = subprocess.run(
                ["setxkbmap", "-query"], capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "layout:" in line.lower():
                        val = line.split(":", 1)[1].strip().lower().split(",")[0]
                        log.info(f"[LAYOUT_DETECT] Detected setxkbmap layout: '{val}'")
                        return val
        except Exception as e:
            log.debug(f"[LAYOUT_DETECT] setxkbmap detection failed: {e}")

        log.info("[LAYOUT_DETECT] Fallback to default layout: 'us'")
        return "us"

    def _get_layout_name(self) -> str:
        cfg_layout = config_manager.get("keyboard_layout", "auto")
        if not cfg_layout:
            cfg_layout = "auto"
        layout = str(cfg_layout).lower()

        if layout == "auto":
            if not self._auto_layout:
                self._auto_layout = self._detect_system_layout()
            return self._auto_layout
        return layout

    def _char_to_key_event(self, char: str) -> Optional[Tuple[int, bool, bool]]:
        layout = self._get_layout_name()

        if self._cached_layout != layout or not self._cached_xkb_map:
            self._cached_xkb_map = _build_dynamic_xkb_map(layout)
            self._cached_layout = layout

        if char in self._cached_xkb_map:
            return self._cached_xkb_map[char]

        # Space / Enter / Tab fallback
        if char == " ":
            return (ecodes.KEY_SPACE, False, False)
        elif char in ("\n", "\r"):
            return (ecodes.KEY_ENTER, False, False)
        elif char == "\t":
            return (ecodes.KEY_TAB, False, False)

        return None

    def _paste_text_via_clipboard(self, text: str):
        """
        Seamlessly pastes text using clipboard insertion (wl-copy / xclip) and Ctrl+V.
        Guarantees 100% seamless support for any language (Arabic, CJK, Emojis) without
        typing hex codes or triggering Enter presses.
        """
        log.info(f"[EVDEV] Pasting text via clipboard: '{text}'")
        from ..core.wayland_utils import clipboard_set_wayland

        success = clipboard_set_wayland(text)
        if not success:
            try:
                import pyperclip

                pyperclip.copy(text)
                success = True
            except Exception as e:
                log.warning(f"[EVDEV] Clipboard copy fallback failed: {e}")

        if success:
            time.sleep(0.02)
            # Emit Ctrl + V over uinput
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
            self.ui.syn()
            time.sleep(0.01)
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
            self.ui.syn()
            time.sleep(0.01)

    def type_text(self, text: str):
        if not self.ui:
            log.warning("[EVDEV] uinput UI device is not initialized.")
            return

        layout = self._get_layout_name()
        log.info(f"[EVDEV] Typing text: '{text}' (Active layout: '{layout}')")

        # Check if text contains non-ASCII or unmapped characters
        has_unmapped = any(self._char_to_key_event(c) is None for c in text)

        if has_unmapped:
            log.info(
                "[EVDEV] Text contains international/unmapped characters. Using seamless clipboard paste."
            )
            self._paste_text_via_clipboard(text)
            return

        # Natively supported characters: type via hardware keycodes
        for char in text:
            event = self._char_to_key_event(char)
            if not event:
                continue

            code, need_shift, need_altgr = event
            key_name = code
            try:
                if hasattr(ecodes, "KEY") and isinstance(ecodes.KEY, dict):
                    key_name = ecodes.KEY.get(code, code)
            except Exception:
                pass

            log.info(
                f"[EVDEV] Char: '{char}' -> KeyCode: {code} ({key_name}), "
                f"Shift: {need_shift}, AltGr: {need_altgr}"
            )

            if need_altgr:
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_RIGHTALT, 1)
                self.ui.syn()

            if need_shift:
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
                self.ui.syn()

            self.ui.write(ecodes.EV_KEY, code, 1)
            self.ui.syn()
            time.sleep(0.01)
            self.ui.write(ecodes.EV_KEY, code, 0)
            self.ui.syn()

            if need_shift:
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
                self.ui.syn()

            if need_altgr:
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_RIGHTALT, 0)
                self.ui.syn()

            time.sleep(0.01)

    def press_key(self, key_str: str, modifiers: List[str] = None):
        if not self.ui:
            log.warning("[EVDEV] uinput UI device is not initialized.")
            return
        try:
            layout = self._get_layout_name()
            mod_map = {
                "ctrl": ecodes.KEY_LEFTCTRL,
                "shift": ecodes.KEY_LEFTSHIFT,
                "alt": ecodes.KEY_LEFTALT,
                "altgr": ecodes.KEY_RIGHTALT,
                "win": ecodes.KEY_LEFTMETA,
                "cmd": ecodes.KEY_LEFTMETA,
                "meta": ecodes.KEY_LEFTMETA,
                "super": ecodes.KEY_LEFTMETA,
            }

            named_keys = {
                "enter": ecodes.KEY_ENTER,
                "esc": ecodes.KEY_ESC,
                "tab": ecodes.KEY_TAB,
                "space": ecodes.KEY_SPACE,
                "backspace": ecodes.KEY_BACKSPACE,
                "delete": ecodes.KEY_DELETE,
                "up": ecodes.KEY_UP,
                "down": ecodes.KEY_DOWN,
                "left": ecodes.KEY_LEFT,
                "right": ecodes.KEY_RIGHT,
                "home": ecodes.KEY_HOME,
                "end": ecodes.KEY_END,
                "pageup": ecodes.KEY_PAGEUP,
                "pagedown": ecodes.KEY_PAGEDOWN,
            }

            mods = [mod_map.get(m.lower(), None) for m in (modifiers or [])]
            mods = [m for m in mods if m is not None]

            main_key = named_keys.get(key_str.lower(), None)
            if main_key is None:
                event = self._char_to_key_event(key_str)
                if event:
                    main_key, extra_shift, extra_altgr = event
                    if extra_shift and ecodes.KEY_LEFTSHIFT not in mods:
                        mods.append(ecodes.KEY_LEFTSHIFT)
                    if extra_altgr and ecodes.KEY_RIGHTALT not in mods:
                        mods.append(ecodes.KEY_RIGHTALT)

            key_name = main_key
            try:
                if hasattr(ecodes, "KEY") and isinstance(ecodes.KEY, dict):
                    key_name = ecodes.KEY.get(main_key, main_key)
            except Exception:
                pass

            log.info(
                f"[EVDEV] PressKey: '{key_str}' -> ResolvedKeyCode: {main_key} ({key_name}), "
                f"Modifiers: {modifiers} -> ResolvedMods: {mods} (Layout: '{layout}')"
            )

            if main_key:
                for m in mods:
                    self.ui.write(ecodes.EV_KEY, m, 1)
                self.ui.write(ecodes.EV_KEY, main_key, 1)
                self.ui.syn()

                self.ui.write(ecodes.EV_KEY, main_key, 0)
                for m in reversed(mods):
                    self.ui.write(ecodes.EV_KEY, m, 0)
                self.ui.syn()
            else:
                log.warning(f"[EVDEV] Unable to resolve keycode for '{key_str}'")
        except Exception as e:
            log.error(f"evdev press_key failed: {e}")

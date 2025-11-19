# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys

class DummyTty:
    """A dummy file-like object to redirect stdout/stderr."""
    def write(self, x): pass
    def flush(self): pass
    def isatty(self): return False

def hide_console_window():
    """
    Hides the console window in frozen (PyInstaller) builds on Windows.

    This should be called as early as possible in the application startup
    to prevent the black console window from flashing briefly.
    """
    if not (sys.platform == "win32" and getattr(sys, "frozen", False)):
        return

    try:
        import ctypes
        
        # Constants from the Windows API
        SW_HIDE = 0
        
        # Get the console window handle and hide it.
        kernel32 = ctypes.windll.kernel32
        console_window = kernel32.GetConsoleWindow()
        if console_window != 0:
            user32 = ctypes.windll.user32
            user32.ShowWindow(console_window, SW_HIDE)
    except Exception:
        # This is a non-critical operation. If it fails, the app can still run.
        pass

def setup_console_redirection():
    """
    Redirects stdout and stderr to a dummy object in frozen builds.

    This prevents any libraries that use print() or logging to the console
    from inadvertently triggering a console window to appear.
    """
    if not getattr(sys, "frozen", False):
        return

    try:
        sys.stdout = DummyTty()
        sys.stderr = DummyTty()
        sys.stdin = DummyTty()
    except Exception:
        pass
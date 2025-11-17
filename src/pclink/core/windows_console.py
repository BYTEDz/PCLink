# src/pclink/core/windows_console.py
"""
PCLink - Windows Console Management
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

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
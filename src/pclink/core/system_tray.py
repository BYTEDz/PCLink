# src/pclink/core/system_tray.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

from .utils import resource_path
from .windows_notifier import WindowsNotifier

TRAY_AVAILABLE = False
IMPORT_ERROR = ""
try:
    import pystray

    TRAY_AVAILABLE = True
except ImportError as e:
    IMPORT_ERROR = str(e)

LINUX_NATIVE_TRAY_AVAILABLE = False
LINUX_TRAY_ERROR = ""
AppIndicator3 = None  # Will be set to whichever library is available

try:
    if sys.platform.startswith('linux'):
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib
        
        # Try AppIndicator3 first (Ubuntu, Linux Mint)
        try:
            gi.require_version('AppIndicator3', '0.1')
            from gi.repository import AppIndicator3 as _AppIndicator
            AppIndicator3 = _AppIndicator
            LINUX_NATIVE_TRAY_AVAILABLE = True
        except (ImportError, ValueError):
            # Fallback to AyatanaAppIndicator3 (Fedora, modern distros)
            try:
                gi.require_version('AyatanaAppIndicator3', '0.1')
                from gi.repository import AyatanaAppIndicator3 as _AppIndicator
                AppIndicator3 = _AppIndicator
                LINUX_NATIVE_TRAY_AVAILABLE = True
            except (ImportError, ValueError) as e:
                LINUX_TRAY_ERROR = f"{e} - Try: sudo dnf install libayatana-appindicator-gtk3 (Fedora) or sudo apt install gir1.2-appindicator3-0.1 (Ubuntu)"
except (ImportError, ValueError) as e:
    LINUX_TRAY_ERROR = f"{e} - Try: sudo dnf install python3-gobject gtk3 (Fedora) or sudo apt install python3-gi gir1.2-gtk-3.0 (Ubuntu)"

log = logging.getLogger(__name__)


class SystemTrayManager:
    """Handles the creation and management of the system tray icon."""

    def __init__(self, controller=None):
        self.controller = controller
        self.icon = None
        self.indicator = None
        self.notifier = None
        if sys.platform == "win32":
            self.notifier = WindowsNotifier()
        self.running = False
        self.use_linux_native = False

        self.gtk_item_start = None
        self.gtk_item_stop = None

        self._check_linux_tray_support()

        if sys.platform.startswith('linux') and LINUX_NATIVE_TRAY_AVAILABLE:
            log.info("Using native Linux AppIndicator for system tray.")
            self.use_linux_native = True
            self.create_linux_indicator()
        elif TRAY_AVAILABLE:
            log.warning(f"Native Linux AppIndicator not available: {LINUX_TRAY_ERROR}")
            log.info("Falling back to pystray for system tray.")
            self.use_linux_native = False
            self.create_pystray_icon()
        else:
            log.warning("No system tray support available (pystray or AppIndicator).")
    
    def _check_linux_tray_support(self):
        if not sys.platform.startswith('linux'):
            return
        if LINUX_NATIVE_TRAY_AVAILABLE:
            log.info("Native Linux AppIndicator support is available.")
        else:
            log.warning(f"Native Linux AppIndicator support not found: {LINUX_TRAY_ERROR}")

    def _get_tray_icon_path(self):
        is_dark_theme = self._is_system_dark_theme()
        if sys.platform == "win32":
            icon_name = 'pclink_dark.ico' if is_dark_theme else 'pclink_light.ico'
            fallback_name = 'icon.ico'
        else:
            icon_name = 'pclink_dark.png' if is_dark_theme else 'pclink_light.png'
            fallback_name = 'icon.png'

        icon_file = resource_path(f"src/pclink/assets/{icon_name}")
        if not icon_file.exists():
            icon_file = resource_path(f"src/pclink/assets/{fallback_name}")
        return icon_file
    
    
    def _is_system_dark_theme(self):
        """Detect if the system is using a dark theme."""
        try:
            if sys.platform == "win32":
                import winreg
                try:
                    # This registry key only exists on Windows 10+
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                    value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
                    winreg.CloseKey(key)
                    return value == 0
                except (FileNotFoundError, OSError):
                    # Windows 8.1 and earlier don't have this key - default to light theme
                    return False
            elif sys.platform.startswith('linux'):
                import subprocess

                def check_gsettings(schema, key):
                    try:
                        res = subprocess.run(
                            ['gsettings', 'get', schema, key],
                            capture_output=True, text=True, timeout=1
                        )
                        if res.returncode == 0:
                            return res.stdout.strip().lower().replace("'", "")
                    except Exception:
                        pass
                    return None

                # 1. Freedesktop Dark Style Preference (Standard)
                # Some desktops expose this via different mechanisms, simplified here for gsettings
                
                # 2. GNOME / Standard GTK
                val = check_gsettings('org.gnome.desktop.interface', 'color-scheme')
                if val and 'dark' in val: return True
                
                # 3. Cinnamon (Linux Mint)
                val = check_gsettings('org.cinnamon.desktop.interface', 'gtk-theme')
                if val and ('dark' in val or 'black' in val): return True

                # 4. MATE (Linux Mint MATE)
                val = check_gsettings('org.mate.interface', 'gtk-theme')
                if val and ('dark' in val or 'black' in val): return True
                
                # 5. Fallback GTK Theme check (GNOME/Other)
                val = check_gsettings('org.gnome.desktop.interface', 'gtk-theme')
                if val and ('dark' in val or 'black' in val): return True
                
                # 6. Check XFCE (xfconf-query) - TODO if requested
                
                # Fallback to dark theme on Linux for compatibility with modern desktop panels.
                return True
        except Exception:
            pass
            
        # Bias toward dark theme on Linux to prevent visibility issues on dark panels.
        # Fallback for old Windows or unexpected errors remains Light.
        if sys.platform.startswith('linux'):
             return True
        return False
    
    def create_pystray_icon(self):
        """Creates the tray icon using the pystray library."""
        if not TRAY_AVAILABLE: return
        try:
            from PIL import Image
            image = Image.open(self._get_tray_icon_path())
            
            menu_items = (
                pystray.MenuItem("Open Web UI", self.open_web_ui, default=True),
                pystray.MenuItem("Mobile API Status", self.show_server_status),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Enable Mobile API", self.start_server, enabled=self.is_server_stopped),
                pystray.MenuItem("Disable Mobile API", self.stop_server, enabled=self.is_server_running),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Restart PCLink", self.restart_server),
                pystray.MenuItem("Exit PCLink", self.quit_application)
            )
            
            menu = pystray.Menu(*menu_items)
            self.icon = pystray.Icon("PCLink", image, "PCLink Server", menu)
        except Exception as e:
            log.error(f"Failed to create pystray icon: {e}", exc_info=True)

    def create_linux_indicator(self):
        """Creates the tray icon using the native AppIndicator3 library."""
        try:
            Gtk.init_check()
            # ID, Icon Name (fallback), Category
            self.indicator = AppIndicator3.Indicator.new("pclink-server", "network-server", AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            
            # Fix: Set Title to avoid "launcher.py" tooltip
            self.indicator.set_title("PCLink")
            # self.indicator.set_label("PCLink", "")  <-- Removed to prevent text next to icon
            
            # Set Icon
            icon_path = str(self._get_tray_icon_path().absolute())
            self.indicator.set_icon_full(icon_path, "PCLink")
            
            menu = Gtk.Menu()
            item_webui = Gtk.MenuItem(label="Open Web UI")
            item_webui.connect("activate", self._linux_open_web_ui)
            menu.append(item_webui)
            
            item_status = Gtk.MenuItem(label="Mobile API Status")
            item_status.connect("activate", self._linux_show_status)
            menu.append(item_status)
            
            menu.append(Gtk.SeparatorMenuItem())
            
            self.gtk_item_start = Gtk.MenuItem(label="Enable Mobile API")
            self.gtk_item_start.connect("activate", self._linux_start_server)
            menu.append(self.gtk_item_start)
            
            self.gtk_item_stop = Gtk.MenuItem(label="Disable Mobile API")
            self.gtk_item_stop.connect("activate", self._linux_stop_server)
            menu.append(self.gtk_item_stop)

            menu.append(Gtk.SeparatorMenuItem())
            item_restart = Gtk.MenuItem(label="Restart PCLink")
            item_restart.connect("activate", self._linux_restart_server)
            menu.append(item_restart)

            item_exit = Gtk.MenuItem(label="Exit PCLink")
            item_exit.connect("activate", self._linux_quit)
            menu.append(item_exit)
            
            menu.show_all()
            self.indicator.set_menu(menu)
            self._update_linux_menu_sensitivity()
        except Exception as e:
            log.error(f"Failed to create Linux AppIndicator: {e}", exc_info=True)
    
    def show(self):
        """Displays the tray icon and starts its event loop in a background thread."""
        if self.use_linux_native and self.indicator:
            self.running = True
            threading.Thread(target=Gtk.main, daemon=True).start()
        elif self.icon:
            self.running = True
            threading.Thread(target=self.icon.run, daemon=True).start()
        else:
            log.warning("System tray not available.")
            
    def hide(self):
        """Hides the tray icon and stops its event loop."""
        if not self.running: return
        try:
            if self.use_linux_native:
                GLib.idle_add(Gtk.main_quit)
            elif self.icon:
                self.icon.stop()
            self.running = False
        except Exception as e:
            log.error(f"Error hiding tray icon: {e}")

    def show_notification(self, title, message):
        # 1. Try Windows Notifier (highest priority on Windows)
        if sys.platform == "win32" and self.notifier and self.notifier.is_available():
            if self.notifier.show(title, message):
                return

        # 2. Try pystray (fallback for Windows, primary for others if available)
        if self.icon and self.running and getattr(pystray.Icon, 'HAS_NOTIFICATION', False):
            self.icon.notify(message, title)
            return

        # 3. Last fallback: Log it
        log.info(f"NOTIFICATION: {title} - {message}")

    def is_server_running(self, item=None):
        return self.controller and self.controller.mobile_api_enabled

    def is_server_stopped(self, item=None):
        return not self.is_server_running()

    def open_web_ui(self, icon=None, item=None):
        if self.controller:
            self.controller.open_web_ui()

    def show_server_status(self, icon=None, item=None):
        status = "Enabled" if self.is_server_running() else "Disabled"
        self.show_notification("PCLink Status", f"Mobile API is {status}")

    def start_server(self, icon=None, item=None):
        if self.controller:
            self.controller.start_mobile_api()
            threading.Timer(0.5, self._update_menu).start()

    def stop_server(self, icon=None, item=None):
        if self.controller:
            self.controller.stop_mobile_api()
            threading.Timer(0.5, self._update_menu).start()

    def restart_server(self, icon=None, item=None):
        if self.controller:
            self.controller.restart()

    def _update_menu(self):
        if self.use_linux_native:
            GLib.idle_add(self._update_linux_menu_sensitivity)
        elif self.icon and self.running:
            self.icon.update_menu()

    def quit_application(self, icon=None, item=None):
        self.hide()
        if self.controller:
            self.controller.shutdown()

    def _update_linux_menu_sensitivity(self):
        if not self.use_linux_native: return
        is_running = self.is_server_running()
        if self.gtk_item_start: self.gtk_item_start.set_sensitive(not is_running)
        if self.gtk_item_stop: self.gtk_item_stop.set_sensitive(is_running)

    def _linux_open_web_ui(self, widget): self.open_web_ui()
    def _linux_show_status(self, widget): self.show_server_status()
    def _linux_start_server(self, widget): self.start_server()
    def _linux_stop_server(self, widget): self.stop_server()
    def _linux_restart_server(self, widget): self.restart_server()
    def _linux_quit(self, widget): self.quit_application()

    def is_tray_available(self):
        return (self.use_linux_native and self.indicator is not None) or \
               (not self.use_linux_native and self.icon is not None)
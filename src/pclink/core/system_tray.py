# src/pclink/core/system_tray.py

"""
System Tray Manager for PCLink
Cross-platform system tray support with Linux AppIndicator fallback
"""

import logging
import threading
import webbrowser
import os
import sys
from pathlib import Path
from .utils import resource_path

# --- Dependency Checks ---
TRAY_AVAILABLE = False
IMPORT_ERROR = ""
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError as e:
    IMPORT_ERROR = str(e)

LINUX_NATIVE_TRAY_AVAILABLE = False
LINUX_TRAY_ERROR = ""
try:
    if sys.platform.startswith('linux'):
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import Gtk, AppIndicator3, GLib
        LINUX_NATIVE_TRAY_AVAILABLE = True
except (ImportError, ValueError) as e:
    LINUX_TRAY_ERROR = f"{e} - Try: sudo apt install python3-gi gir1.2-appindicator3-0.1"

log = logging.getLogger(__name__)


class SystemTrayManager:
    def __init__(self, controller=None):
        self.controller = controller
        self.icon = None
        self.indicator = None
        self.running = False
        self.use_linux_native = False

        # GTK Menu Items for dynamic updates
        self.gtk_item_start = None
        self.gtk_item_stop = None
        self.gtk_item_restart = None

        self._check_linux_tray_support()

        if sys.platform.startswith('linux') and LINUX_NATIVE_TRAY_AVAILABLE:
            log.info("Using native Linux AppIndicator for system tray.")
            self.use_linux_native = True
            self.create_linux_indicator()
        elif TRAY_AVAILABLE:
            log.warning(f"Native Linux AppIndicator not available: {LINUX_TRAY_ERROR}")
            log.info("Falling back to pystray for system tray")
            self.use_linux_native = False
            self.create_pystray_icon()
        else:
            log.warning("No system tray support available (pystray or AppIndicator).")
    
    def _get_real_controller(self):
        """Safely gets the actual PCLink Controller instance."""
        if self.controller and hasattr(self.controller, 'controller'):
            return self.controller.controller
        return None

    def _check_linux_tray_support(self):
        """Check Linux system tray support and provide detailed guidance."""
        if not sys.platform.startswith('linux'):
            return
        desktop_env = os.environ.get('XDG_CURRENT_DESKTOP', 'unknown').lower()
        log.info(f"Detected Linux desktop environment: {desktop_env}")
        if LINUX_NATIVE_TRAY_AVAILABLE:
            log.info("SUCCESS: Native Linux AppIndicator support is available.")
        else:
            log.warning("INFO: Native Linux AppIndicator support not found.")
            log.warning(f"  -> Reason: {LINUX_TRAY_ERROR}")
            log.warning("  -> For full menu support, run: sudo apt install python3-gi gir1.2-appindicator3-0.1")
        if TRAY_AVAILABLE:
            log.info("INFO: pystray fallback library is available.")
        else:
            log.warning(f"ERROR: pystray library not available: {IMPORT_ERROR}")

    def create_pystray_icon(self):
        """Create a tray icon and its context menu using pystray."""
        if not TRAY_AVAILABLE:
            return
        try:
            # This full path is correct because our new resource_path in utils.py handles it.
            if sys.platform == "win32":
                icon_file = resource_path("src/pclink/assets/icon.ico")
            else:
                icon_file = resource_path("src/pclink/assets/icon.png")
            
            image = Image.open(icon_file) if icon_file.exists() else self.create_simple_icon()
            
            # Define menu structure based on platform and capabilities
            if sys.platform == "win32":
                menu_items = (
                    pystray.MenuItem("Open Web UI", self.open_web_ui, default=True),
                    pystray.MenuItem("Remote API Status", self.show_server_status),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Start Remote API", self.start_server, enabled=self.is_server_stopped),
                    pystray.MenuItem("Stop Remote API", self.stop_server, enabled=self.is_server_running),
                    pystray.MenuItem("Restart Remote API", self.restart_server, enabled=self.is_server_running),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit PCLink", self.quit_application)
                )
            else: # Linux pystray fallback
                if getattr(pystray.Icon, 'HAS_MENU', False):
                    menu_items = (
                        pystray.MenuItem("Open Web UI", self.open_web_ui, default=True),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("Exit PCLink", self.quit_application)
                    )
                else:
                    log.warning("pystray backend does not support menus on this system (likely Xorg).")
                    menu_items = (pystray.MenuItem("Open Web UI", self.open_web_ui, default=True),)
            
            menu = pystray.Menu(*menu_items)
            self.icon = pystray.Icon("PCLink", image, "PCLink Server", menu)
            log.info("pystray icon created successfully.")
        except Exception as e:
            log.error(f"Failed to create pystray icon: {e}", exc_info=True)
            self.icon = None

    def create_linux_indicator(self):
        """Create Linux AppIndicator3 tray icon with a full, clean context menu."""
        try:
            if not Gtk.init_check()[0]:
                log.error("Failed to initialize GTK for AppIndicator")
                return
            
            self.indicator = AppIndicator3.Indicator.new(
                "pclink-server", "network-server", AppIndicator3.IndicatorCategory.APPLICATION_STATUS
            )
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            
            # This full path is correct because our new resource_path in utils.py handles it.
            icon_path = str(resource_path("src/pclink/assets/icon.png").absolute())
            self.indicator.set_icon_full(icon_path, "PCLink Icon")
            
            menu = Gtk.Menu()
            
            item_webui = Gtk.MenuItem(label="Open Web UI")
            item_webui.connect("activate", self._linux_open_web_ui)
            menu.append(item_webui)
            
            item_status = Gtk.MenuItem(label="Remote API Status")
            item_status.connect("activate", self._linux_show_status)
            menu.append(item_status)
            
            menu.append(Gtk.SeparatorMenuItem())
            
            self.gtk_item_start = Gtk.MenuItem(label="Start Remote API")
            self.gtk_item_start.connect("activate", self._linux_start_server)
            menu.append(self.gtk_item_start)
            
            self.gtk_item_stop = Gtk.MenuItem(label="Stop Remote API")
            self.gtk_item_stop.connect("activate", self._linux_stop_server)
            menu.append(self.gtk_item_stop)

            self.gtk_item_restart = Gtk.MenuItem(label="Restart Remote API")
            self.gtk_item_restart.connect("activate", self._linux_restart_server)
            menu.append(self.gtk_item_restart)

            menu.append(Gtk.SeparatorMenuItem())
            
            item_exit = Gtk.MenuItem(label="Exit PCLink")
            item_exit.connect("activate", self._linux_quit)
            menu.append(item_exit)
            
            menu.show_all()
            self.indicator.set_menu(menu)
            
            self._update_linux_menu_sensitivity()
            
            log.info("Native Linux AppIndicator created successfully with a full context menu.")
        except Exception as e:
            log.error(f"Failed to create Linux AppIndicator: {e}", exc_info=True)
            self.indicator = None
            if TRAY_AVAILABLE:
                log.warning("Falling back to pystray due to AppIndicator error.")
                self.use_linux_native = False
                self.create_pystray_icon()

    def create_simple_icon(self):
        log.warning("Icon file not found, creating fallback icon.")
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle([10, 15, 54, 40], fill=(70, 130, 180))
        draw.rectangle([14, 19, 50, 36], fill=(30, 30, 30))
        return image
    
    def show(self):
        if self.use_linux_native:
            if self.indicator:
                self.running = True
                log.info("Starting GTK main loop for AppIndicator...")
                threading.Thread(target=Gtk.main, daemon=True).start()
        else:
            if not self.icon:
                log.warning("System tray not available, running without tray icon.")
                return
            log.info("Starting pystray system tray icon...")
            self.running = True
            threading.Thread(target=self.icon.run, daemon=True).start()
            
    def hide(self):
        if not self.running: return
        try:
            if self.use_linux_native:
                GLib.idle_add(Gtk.main_quit)
            elif self.icon:
                self.icon.stop()
            self.running = False
            log.info("System tray has been stopped.")
        except Exception as e:
            log.error(f"Error while hiding tray icon: {e}")

    def setup_menu(self, mode="headless"):
        log.debug(f"Tray menu setup for {mode} mode (already configured).")

    def show_notification(self, title, message):
        if self.icon and self.running and getattr(pystray.Icon, 'HAS_NOTIFICATION', False):
            try:
                self.icon.notify(message, title)
                return
            except Exception: pass # Fallback to notify-send
        if sys.platform.startswith('linux'):
            self._show_linux_notification(title, message)
        else:
            log.info(f"NOTIFICATION (Tray not visible/supported): {title} - {message}")
    
    def _show_linux_notification(self, title, message):
        try:
            import subprocess
            subprocess.run(['notify-send', '--app-name=PCLink', title, message], check=False, timeout=2)
        except (FileNotFoundError, subprocess.SubprocessError):
            log.info(f"NOTIFICATION: {title} - {message}")

    def is_server_running(self, item=None):
        real_controller = self._get_real_controller()
        return real_controller and getattr(real_controller, 'mobile_api_enabled', False)

    def is_server_stopped(self, item=None):
        return not self.is_server_running()

    def open_web_ui(self, icon=None, item=None):
        log.info("Tray: Open Web UI clicked")
        try:
            real_controller = self._get_real_controller()
            port = real_controller.get_port() if real_controller else 38080
            url = f'https://localhost:{port}/'
            webbrowser.open(url)
        except Exception as e:
            log.error(f"Error opening web UI: {e}")

    def show_server_status(self, icon=None, item=None):
        log.info("Tray: Show Remote API Status clicked")
        status = "Running" if self.is_server_running() else "Stopped"
        self.show_notification("PCLink Status", f"Remote API is {status}")

    def start_server(self, icon=None, item=None):
        log.info("Tray: Start Remote API clicked")
        real_controller = self._get_real_controller()
        if real_controller and self.is_server_stopped():
            real_controller.start_server()
            threading.Timer(0.5, self._update_menu).start()

    def stop_server(self, icon=None, item=None):
        log.info("Tray: Stop Remote API clicked")
        real_controller = self._get_real_controller()
        if real_controller and self.is_server_running():
            real_controller.stop_server()
            threading.Timer(0.5, self._update_menu).start()

    def restart_server(self, icon=None, item=None):
        log.info("Tray: Restart Remote API clicked")
        if self.is_server_running():
            real_controller = self._get_real_controller()
            if real_controller:
                real_controller.stop_server()
                threading.Timer(1.0, real_controller.start_server).start()
                threading.Timer(1.5, self._update_menu).start()
    
    def _update_menu(self):
        """Force update the tray menu to reflect current state."""
        if self.use_linux_native:
            GLib.idle_add(self._update_linux_menu_sensitivity)
        elif self.icon and self.running:
            try:
                self.icon.update_menu()
            except Exception as e:
                log.warning(f"Failed to update pystray menu: {e}")

    def quit_application(self, icon=None, item=None):
        log.info("Tray: Exit PCLink clicked")
        self.hide()
        def do_quit():
            try:
                real_controller = self._get_real_controller()
                if real_controller: real_controller.stop_server_completely()
            finally:
                os._exit(0)
        threading.Timer(0.5, do_quit).start()

    def update_status(self, status: str, port: int = None):
        self._update_menu()
        if self.icon and not self.use_linux_native:
            title = f"PCLink Server - {status.title()}"
            if port: title += f" (Port {port})"
            self.icon.title = title
    
    def update_server_status(self, status: str): self.update_status(status)
    def show_message(self, title, message, icon=None): self.show_notification(title, message)
    
    def _update_linux_menu_sensitivity(self):
        if not self.use_linux_native: return
        is_running = self.is_server_running()
        if self.gtk_item_start: self.gtk_item_start.set_sensitive(not is_running)
        if self.gtk_item_stop: self.gtk_item_stop.set_sensitive(is_running)
        if self.gtk_item_restart: self.gtk_item_restart.set_sensitive(is_running)

    def _linux_open_web_ui(self, widget): self.open_web_ui()
    def _linux_show_status(self, widget): self.show_server_status()
    def _linux_start_server(self, widget): self.start_server()
    def _linux_stop_server(self, widget): self.stop_server()
    def _linux_restart_server(self, widget): self.restart_server()
    def _linux_quit(self, widget): self.quit_application()

    def is_tray_available(self):
        return (self.use_linux_native and self.indicator) or (not self.use_linux_native and self.icon)

def create_system_tray(controller=None):
    return SystemTrayManager(controller)
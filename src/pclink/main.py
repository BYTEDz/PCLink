# filename: src/pclink/main.py
#!/usr/bin/env python3
"""
PCLink - Remote PC Control Server
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

import asyncio
import logging
import multiprocessing
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.config import config_manager
from .core.logging_config import setup_logging
from .core.singleton import PCLinkSingleton
from .core.utils import run_preflight_checks
from .core.version import __app_name__, __version__
from .gui.main_window import MainWindow
from .gui.theme import create_app_icon, get_stylesheet
from .headless import HeadlessApp


def detect_startup_mode() -> bool:
    """
    Determines if the application should start in headless/background mode.
    This is typically true when launched on system startup.
    """
    return "--startup" in sys.argv


def main() -> int:
    """Main entry point for the application."""
    multiprocessing.freeze_support()
    
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        from .core.windows_console import hide_console_window
        hide_console_window()

    # Run pre-flight checks to create directories and certificates before anything else.
    run_preflight_checks()
    setup_logging()
    log = logging.getLogger(__name__)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    is_headless_mode_request = detect_startup_mode() # Determine mode early

    singleton = PCLinkSingleton()
    if not singleton.acquire_lock():
        log.warning("Another PCLink instance is already running.")
        if is_headless_mode_request:
            # If a headless instance is requested, but another is already running,
            # we should not show a pop-up. The existing instance is responsible.
            log.info("Headless startup detected, exiting silently as another instance is running.")
            return 0 # Exit gracefully, assuming the other instance is the active one
        else:
            # If a manual GUI launch, inform the user.
            try:
                temp_app = QApplication.instance() or QApplication([])
                QMessageBox.information(None, "PCLink", "PCLink is already running. Check the system tray.")
            except Exception:
                pass
            return 1 # Exit with error code for manual GUI attempt
        
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(__app_name__)
        app.setApplicationVersion(__version__)
        app.setOrganizationName("BYTEDz")
        
        app.setStyleSheet(get_stylesheet())
        app.setWindowIcon(create_app_icon())

        # Now use the determined mode
        main_component = HeadlessApp() if is_headless_mode_request else MainWindow()

        if not is_headless_mode_request:
            from .core.setup_guide import should_show_setup_guide, show_setup_guide
            if should_show_setup_guide():
                if show_setup_guide(main_component):
                    # If setup completes successfully, restart the server to apply settings
                    main_component.controller.stop_server()
                    QTimer.singleShot(500, main_component.controller.start_server)
            main_component.show()

        log.info(f"PCLink v{__version__} started in {'headless' if is_headless_mode_request else 'GUI'} mode.")

        exit_code = app.exec()
        log.info(f"Application exiting with code {exit_code}.")
        return exit_code

    except Exception as e:
        log.critical("A fatal error occurred during application startup.", exc_info=True)
        try:
            QMessageBox.critical(None, "Fatal Error", f"PCLink failed to start:\n{e}")
        except Exception:
            pass
        return 1
    finally:
        singleton.release_lock()


if __name__ == "__main__":
    sys.exit(main())

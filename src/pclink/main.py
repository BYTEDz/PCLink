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

import logging
import sys

from .core.config import config_manager
from .core.constants import APP_AUMID
from .core.logging import setup_logging
from .core.singleton import PCLinkSingleton
from .core.utils import run_preflight_checks
from .core.version import __app_name__, __version__
from .headless import HeadlessApp


def detect_startup_mode() -> bool:
    """Determines if the application should start in headless/background mode."""
    return "--startup" in sys.argv


def show_help():
    """Display help information."""
    print(f"{__app_name__} v{__version__}")
    print("Remote PC Control Server with Web Interface")
    print("")
    print("Usage:")
    print("   pclink                    # Start with web UI (default)")
    print("   pclink --startup          # Headless background mode")
    print("   pclink --no-browser       # Don't auto-open browser")
    print("   pclink --help             # Show this help")
    print("")


def main() -> int:
    """Main entry point for PCLink."""
    
    # Handle help request
    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()
        return 0
    
    # Set up logging
    setup_logging()
    log = logging.getLogger(__name__)
    
    log.info(f"Starting {__app_name__} v{__version__}")
    
    # Run preflight checks
    if not run_preflight_checks():
        log.error("Preflight checks failed")
        return 1
    
    # Determine startup mode
    is_headless_mode_request = detect_startup_mode()
    
    # Check if another instance is already running
    singleton = PCLinkSingleton()
    if not singleton.acquire_lock():
        log.info("Another PCLink instance is already running.")
        
        if is_headless_mode_request:
            log.info("Headless startup detected, exiting silently as another instance is running.")
            return 0
        else:
            print("PCLink is already running. Check the system tray.")
            return 1
    
    # Start PCLink in web-first mode
    log.info("Starting PCLink in web-first mode...")
    
    try:
        main_component = HeadlessApp()
        
        # Show setup guide if needed (for non-headless mode)
        if not is_headless_mode_request:
            from .core.setup_guide import should_show_setup_guide, show_setup_guide
            if should_show_setup_guide():
                if show_setup_guide(main_component):
                    log.info("Setup guide completed successfully")
                else:
                    log.warning("Setup guide was cancelled or failed")
        
        return main_component.run()
        
    except Exception as e:
        log.critical(f"Failed to start PCLink: {e}")
        print(f"ERROR: Could not start PCLink: {e}")
        return 1
    finally:
        singleton.release_lock()


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
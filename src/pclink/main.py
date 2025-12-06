# src/pclink/main.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import sys
import threading

from .core.config import config_manager
from .core.logging import setup_logging
from .core.server_controller import ServerController
from .core.singleton import PCLinkSingleton
from .core.system_tray import SystemTrayManager
from .core.utils import run_preflight_checks
from .core.version import __app_name__, __version__


def main() -> int:
    # Fix for Windows 8.1 asyncio issues - use SelectorEventLoop instead of ProactorEventLoop
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            # Fallback for older Python versions
            pass
    
    setup_logging()
    log = logging.getLogger(__name__)
    
    log.info(f"Starting {__app_name__} v{__version__}")
    
    if not run_preflight_checks():
        log.error("Preflight checks failed")
        return 1
    
    singleton = PCLinkSingleton()
    if not singleton.acquire_lock():
        log.warning("Another PCLink instance is already running. Exiting.")
        print("PCLink is already running. Use 'pclink status' or check the system tray.")
        return 1

    tray_manager = None
    controller = None
    shutdown_event = threading.Event()

    def graceful_shutdown():
        log.info("Graceful shutdown initiated.")
        if tray_manager:
            tray_manager.hide()
        shutdown_event.set()

    try:
        controller = ServerController(shutdown_callback=graceful_shutdown)
        controller.start()
        
        tray_enabled = config_manager.get("enable_tray_icon", True)
        if tray_enabled:
            log.info("System tray is enabled. Initializing...")
            tray_manager = SystemTrayManager(controller)
        else:
            log.info("System tray is disabled by user configuration.")
            tray_manager = None

        if tray_manager and tray_manager.is_tray_available():
            tray_manager.show()
            log.info("PCLink is running with an active system tray icon.")
            shutdown_event.wait()
        else:
            if tray_enabled:
                log.warning("System tray UI could not be created or is unavailable.")
            log.warning("PCLink is running in headless mode.")
            shutdown_event.wait()
        
        log.info("Main thread is exiting.")
        return 0

    except KeyboardInterrupt:
        log.info("Keyboard interrupt received, shutting down.")
        return 0
    except Exception as e:
        log.critical(f"A critical error occurred in the main application loop: {e}", exc_info=True)
        return 1
    finally:
        if controller:
            controller.shutdown()
        singleton.release_lock()
        os._exit(0)
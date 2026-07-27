# src/pclink/main.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import logging
import multiprocessing
import os
import sys
import threading

from .core.config import config_manager
from .core.logging import setup_logging
from .core.notifier import get_system_notifier
from .core.server_controller import ServerController
from .core.singleton import PCLinkSingleton
from .core.system_tray import SystemTrayManager
from .core.utils import run_preflight_checks
from .core.version import __app_name__, __version__
from .services import macro_service

_ = gettext.gettext


def main() -> int:
    multiprocessing.freeze_support()

    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            pass

    setup_logging()
    log = logging.getLogger(__name__)

    log.info(_("Starting {} v{}").format(__app_name__, __version__))

    if not run_preflight_checks():
        log.error(_("Preflight checks failed"))
        return 1

    singleton = PCLinkSingleton()
    if not singleton.acquire_lock():
        log.warning(_("Another PCLink instance is already running. Exiting."))
        print(
            _(
                "PCLink is already running. Use 'pclink status' or check the system tray."
            )
        )
        return 1

    tray_manager = None
    controller = None
    shutdown_event = threading.Event()

    def graceful_shutdown():
        log.info(_("Graceful shutdown initiated."))
        if tray_manager:
            tray_manager.hide()
        shutdown_event.set()

    try:
        controller = ServerController(shutdown_callback=graceful_shutdown)
        controller.start()

        tray_enabled = config_manager.get("enable_tray_icon", True)
        if tray_enabled:
            log.info(_("System tray is enabled. Initializing..."))
            tray_manager = SystemTrayManager(controller)
        else:
            log.info(_("System tray is disabled by user configuration."))
            tray_manager = None

        def macro_notification_handler(title, message):
            if tray_manager:
                tray_manager.show_notification(title, message)
            else:
                fallback_notifier = get_system_notifier()
                if fallback_notifier.is_available():
                    fallback_notifier.show(title, message)
                else:
                    log.info(
                        _("NOTIFICATION (Headless): {} - {}").format(title, message)
                    )

        macro_service.set_notification_handler(macro_notification_handler)

        if tray_manager and tray_manager.is_tray_available():
            tray_manager.show()
            log.info(_("PCLink is running with an active system tray icon."))
            shutdown_event.wait()
        else:
            if tray_enabled:
                log.warning(_("System tray UI could not be created or is unavailable."))
            log.warning(_("PCLink is running in headless mode."))
            shutdown_event.wait()

        log.info(_("Main thread is exiting."))
        return 0

    except KeyboardInterrupt:
        log.info(_("Keyboard interrupt received, shutting down."))
        return 0
    except Exception as e:
        log.critical(
            _("A critical error occurred in the main application loop: {}").format(e),
            exc_info=True,
        )
        return 1
    finally:
        if controller:
            controller.shutdown()
        singleton.release_lock()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())

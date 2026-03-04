# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys
import os
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import logging
import threading
from pathlib import Path

# Add src to sys.path to allow imports when running as a service
current_dir = Path(__file__).parent.parent.parent.absolute()
src_dir = current_dir / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

try:
    from pclink.main import main as pclink_main
    from pclink.core import constants
except ImportError:
    # Fallback for different execution contexts
    pass

class PCLinkService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PCLinkService"
    _svc_display_name_ = "PCLink Server Service"
    _svc_description_ = "Ensures PCLink Server runs as a background service on Windows boot."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.is_running = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.is_running = False
        
        # Trigger PCLink shutdown if possible
        try:
            import requests
            requests.post(f"http://127.0.0.1:{constants.CONTROL_PORT}/stop", timeout=1)
        except Exception:
            pass

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ""))
        self.main()

    def main(self):
        # Run PCLink in a separate thread so we can monitor the stop event
        server_thread = threading.Thread(target=self.run_pclink)
        server_thread.daemon = True
        server_thread.start()
        
        # Wait for the stop event
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STOPPED,
                              (self._svc_name_, ""))

    def run_pclink(self):
        try:
            # Set up environment variables if needed
            os.environ["PCLINK_SERVICE"] = "1"
            pclink_main()
        except Exception as e:
            logging.error(f"PCLink Service Error: {e}")
            self.SvcStop()

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(PCLinkService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(PCLinkService)

# src/pclink/services/terminal_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import platform
import subprocess
import sys
from typing import List, Dict, Optional, Any

log = logging.getLogger(__name__)

# Conditional import for PTY on non-Windows systems.
if platform.system() != "Windows":
    import pty
else:
    import threading

class TerminalService:
    """Logic for terminal shell management and platform-specific I/O bridging."""

    def get_available_shells(self) -> Dict[str, Any]:
        """Detects available shells on the system."""
        if platform.system() == "Windows":
            shells = ["cmd"]
            # Check for powershell
            try:
                if subprocess.run(["powershell", "-Command", "Get-Host"], capture_output=True, timeout=1).returncode == 0:
                    shells.append("powershell")
            except Exception: pass
            
            try:
                if subprocess.run(["pwsh", "-Version"], capture_output=True, timeout=1).returncode == 0:
                    if "powershell" not in shells: shells.append("powershell")
            except Exception: pass
                
            return {"shells": shells, "default": "cmd"}
        else:
            available = []
            for s in ["bash", "sh", "zsh", "fish"]:
                try:
                    if subprocess.run(["which", s], capture_output=True, timeout=1).returncode == 0:
                        available.append(s)
                except Exception: pass
            
            default = os.environ.get("SHELL", "bash").split("/")[-1]
            return {"shells": available, "default": default}

    async def run_windows_terminal(self, websocket: Any, shell_type: str = "cmd"):
        """Bridging Windows terminal I/O over WebSocket."""
        # This implementation remains a bridge between subprocess and websocket
        # but is encapsulated here for reuse and cleaner router logic.
        
        # Select shell command
        shell_cmd = ["cmd"]
        if shell_type.lower() == "powershell":
            # Check for pwsh first
            try:
                if subprocess.run(["pwsh", "-Version"], capture_output=True, timeout=1).returncode == 0:
                    shell_cmd = ["pwsh", "-NoLogo", "-ExecutionPolicy", "Bypass"]
                else:
                    shell_cmd = ["powershell", "-NoLogo", "-ExecutionPolicy", "Bypass"]
            except Exception:
                shell_cmd = ["powershell", "-NoLogo", "-ExecutionPolicy", "Bypass"]

        try:
            process = subprocess.Popen(
                shell_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=False,
                bufsize=0
            )
            
            msg = f"\r\n[PCLink Terminal] Connected to {'PowerShell' if 'power' in shell_type else 'Command Prompt'}\r\n"
            await websocket.send_text(msg)
            
            loop = asyncio.get_event_loop()

            async def output_reader():
                while process.poll() is None:
                    try:
                        data = await loop.run_in_executor(None, lambda: process.stdout.read(512) if process.stdout else b"")
                        if data: await websocket.send_bytes(data)
                        else: await asyncio.sleep(0.05)
                    except Exception: break

            input_task = asyncio.create_task(output_reader())

            try:
                while process.poll() is None:
                    message = await websocket.receive()
                    if message["type"] == "websocket.receive":
                        data = message.get("bytes") or message.get("text", "").encode("utf-8")
                        if data and process.stdin:
                            await loop.run_in_executor(None, lambda d=data: (process.stdin.write(d), process.stdin.flush()))
            except Exception: pass
            finally:
                input_task.cancel()
                if process.poll() is None:
                    try:
                        process.terminate()
                        await asyncio.sleep(0.5)
                        if process.poll() is None: process.kill()
                    except Exception: pass
        except Exception as e:
            log.error(f"Windows terminal failed: {e}")
            raise

    async def run_unix_terminal(self, websocket: Any):
        """Bridging Unix/Linux terminal I/O via PTY over WebSocket."""
        shell = os.environ.get("SHELL", "bash")
        master_fd = None
        try:
            master_fd, slave_fd = pty.openpty()
            process = await asyncio.create_subprocess_exec(
                shell,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid
            )
            os.close(slave_fd)
            
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader(loop=loop)
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, os.fdopen(master_fd, "rb", 0))

            async def forward():
                while not reader.at_eof():
                    try:
                        data = await reader.read(1024)
                        if data: await websocket.send_bytes(data)
                    except Exception: break

            fwd_task = asyncio.create_task(forward())

            try:
                while process.returncode is None:
                    data = await websocket.receive_bytes()
                    os.write(master_fd, data)
            except Exception: pass
            finally:
                fwd_task.cancel()
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
        except Exception as e:
            log.error(f"Unix terminal failed: {e}")
            raise
        finally:
            if master_fd is not None:
                try: os.close(master_fd)
                except Exception: pass

# Global instance
terminal_service = TerminalService()

# src/pclink/services/terminal_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import platform
import subprocess
import sys
from typing import Any, Dict

log = logging.getLogger(__name__)

# Conditional import for PTY on non-Windows systems.
if platform.system() != "Windows":
    import pty
else:
    pass

SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


class TerminalService:
    """Logic for terminal shell management and platform-specific I/O bridging."""

    def get_available_shells(self) -> Dict[str, Any]:
        """Detects available shells on the system."""
        if platform.system() == "Windows":
            return {"shells": ["cmd"], "default": "cmd"}
        else:
            available = []
            for s in ["bash", "sh", "zsh", "fish"]:
                try:
                    if (
                        subprocess.run(
                            ["which", s],
                            capture_output=True,
                            timeout=1,
                            creationflags=SUBPROCESS_FLAGS,
                        ).returncode
                        == 0
                    ):
                        available.append(s)
                except Exception:
                    pass

            default = os.environ.get("SHELL", "bash").split("/")[-1]
            return {"shells": available, "default": default}

    async def run_windows_terminal(self, websocket: Any, shell_type: str = "cmd"):
        """Bridging Windows terminal I/O over WebSocket with non-blocking asyncio."""
        shell_cmd = "cmd.exe"
        shell_args = []

        try:
            process = await asyncio.create_subprocess_exec(
                shell_cmd,
                *shell_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            async def output_reader():
                try:
                    while True:
                        data = await process.stdout.read(1024)
                        if not data:
                            break
                        await websocket.send_bytes(data)
                except Exception:
                    pass

            out_task = asyncio.create_task(output_reader())

            typed_chars = 0

            try:
                while process.returncode is None:
                    message = await websocket.receive()
                    if message["type"] == "websocket.receive":
                        data = message.get("bytes") or message.get("text", "").encode(
                            "utf-8"
                        )
                        if data:
                            is_backspace = data == b"\x7f" or data == b"\x08"

                            if is_backspace:
                                if typed_chars <= 0:
                                    continue  # Protect the prompt
                                typed_chars -= 1
                                echo_data = b"\x08 \x08"
                            else:
                                if b"\r" in data or b"\n" in data:
                                    typed_chars = 0
                                    # Parse data to correct newlines for Windows pipe
                                    if b"\r" in data and b"\n" not in data:
                                        data = data.replace(b"\r", b"\r\n")
                                else:
                                    typed_chars += len(data.replace(b"\x1b", b""))
                                echo_data = data

                            process.stdin.write(data)
                            await process.stdin.drain()

                            # Manual echo visual feedback
                            try:
                                await websocket.send_bytes(echo_data)
                            except Exception:
                                pass
                    elif message["type"] == "websocket.disconnect":
                        break

            except Exception:
                pass
            finally:
                out_task.cancel()
                if process.returncode is None:
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                    except Exception:
                        if process.returncode is None:
                            try:
                                process.kill()
                            except Exception:
                                pass
        except Exception as e:
            log.error(f"Windows terminal failed: {e}")
            raise

    async def run_unix_terminal(self, websocket: Any, shell_type: str = "bash"):
        """Bridging Unix/Linux terminal I/O via PTY over WebSocket."""
        # Compatibility: If client is old or Windows-style, "cmd" means default shell on Unix
        shell = shell_type
        if not shell or shell in ["default", "cmd"]:
            shell = os.environ.get("SHELL", "bash")

        master_fd = None
        try:
            master_fd, slave_fd = pty.openpty()
            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            process = await asyncio.create_subprocess_exec(
                shell,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                preexec_fn=os.setsid,
            )
            os.close(slave_fd)

            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader(loop=loop)
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(
                lambda: protocol, os.fdopen(master_fd, "rb", 0)
            )

            async def forward():
                while not reader.at_eof():
                    try:
                        data = await reader.read(1024)
                        if data:
                            await websocket.send_bytes(data)
                    except Exception:
                        break

            fwd_task = asyncio.create_task(forward())

            try:
                while process.returncode is None:
                    data = await websocket.receive_bytes()
                    os.write(master_fd, data)
            except Exception:
                pass
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
                try:
                    os.close(master_fd)
                except Exception:
                    pass


# Global instance
terminal_service = TerminalService()

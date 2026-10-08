# src/pclink/services/terminal_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import collections
import json
import logging
import os
import platform
import shutil
import subprocess
import time
from typing import Any, Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

if platform.system() != "Windows":
    import fcntl
    import pty
    import struct
    import termios


class PersistentTerminalSession:
    """Represents a long-lived terminal shell decoupled from client connections."""

    def __init__(self, session_id: str, shell_type: str):
        self.session_id = session_id
        self.shell_type = shell_type
        self.process: Optional[asyncio.subprocess.Process] = None
        self.websocket: Optional[WebSocket] = None
        # Circular buffer keeping the last 1,000 output chunks (~500 KB) for replay
        self.output_buffer: collections.deque = collections.deque(maxlen=1000)
        self.master_fd: Optional[int] = None
        self.transport: Optional[asyncio.BaseTransport] = None
        self.cols: int = 80
        self.rows: int = 24
        self.created_at: float = time.time()
        self.last_active: float = time.time()
        self.reader_task: Optional[asyncio.Task] = None

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def set_size(self, cols: int, rows: int):
        """Sets the PTY window size and notifies the shell via SIGWINCH."""
        self.cols = max(1, cols)
        self.rows = max(1, rows)

        if self.master_fd is not None and platform.system() != "Windows":
            try:
                winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
                log.debug(
                    f"Terminal session '{self.session_id}' resized to {self.cols}x{self.rows}"
                )
            except Exception as e:
                log.debug(f"Failed to set PTY window size: {e}")

    async def broadcast_output(self, data: bytes):
        """Buffers output and streams it to the currently attached WebSocket if present."""
        self.output_buffer.append(data)
        self.last_active = time.time()
        if self.websocket:
            try:
                await self.websocket.send_bytes(data)
            except Exception:
                self.websocket = None

    async def terminate(self):
        """Forcefully kills the underlying process and safely unregisters transport."""
        if self.reader_task and not self.reader_task.done():
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass

        if self.process and self.process.returncode is None:
            try:
                if platform.system() == "Windows":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        self.process.kill()
            except Exception:
                pass

        # Let the asyncio transport close the file descriptor cleanly to prevent Errno 9
        if self.transport:
            try:
                self.transport.close()
            except Exception:
                pass
            self.transport = None
            self.master_fd = None
        elif self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None

        if self.websocket:
            try:
                await self.websocket.close(code=1000)
            except Exception:
                pass
            self.websocket = None


class TerminalService:
    """Manages persistent terminal shells and client connection attach/detach."""

    def __init__(self):
        self._sessions: Dict[str, PersistentTerminalSession] = {}

    def get_available_shells(self) -> Dict[str, Any]:
        """Detects available shells on the system."""
        if platform.system() == "Windows":
            return {"shells": ["cmd"], "default": "cmd"}
        else:
            available = []
            for s in ["bash", "sh", "zsh", "fish"]:
                if shutil.which(s):
                    available.append(s)

            default = os.environ.get("SHELL", "bash").split("/")[-1]
            if default not in available and shutil.which(default):
                available.append(default)

            return {"shells": available, "default": default or "bash"}

    async def terminate_all_sessions(self):
        """Invoked by Global Kill Switch: Terminate all running shell processes."""
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            await session.terminate()

    async def kill_session(self, session_id: str):
        """Explicitly terminates a single persistent session."""
        session = self._sessions.pop(session_id, None)
        if session:
            await session.terminate()

    async def _spawn_windows_process(self, session: PersistentTerminalSession):
        shell_cmd = "cmd.exe" if session.shell_type == "cmd" else "cmd.exe"
        session.process = await asyncio.create_subprocess_exec(
            shell_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        async def _reader():
            try:
                while session.is_alive:
                    data = await session.process.stdout.read(1024)
                    if not data:
                        break
                    await session.broadcast_output(data)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug(f"Windows terminal reader error: {e}")
            finally:
                if self._sessions.get(session.session_id) is session:
                    self._sessions.pop(session.session_id, None)
                if session.websocket:
                    try:
                        await session.broadcast_output(
                            b"\r\n\r\n[Process completed]\r\n"
                        )
                    except Exception:
                        pass
                asyncio.create_task(session.terminate())

        session.reader_task = asyncio.create_task(_reader())

    async def _spawn_unix_process(self, session: PersistentTerminalSession):
        shell_path = (
            shutil.which(session.shell_type)
            or os.environ.get("SHELL")
            or shutil.which("bash")
            or "/bin/sh"
        )
        master_fd, slave_fd = pty.openpty()
        session.master_fd = master_fd

        if session.cols > 0 and session.rows > 0:
            session.set_size(session.cols, session.rows)

        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")

        session.process = await asyncio.create_subprocess_exec(
            shell_path,
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
        transport, _ = await loop.connect_read_pipe(
            lambda: protocol, os.fdopen(master_fd, "rb", 0)
        )
        session.transport = transport

        async def _reader():
            try:
                while not reader.at_eof() and session.is_alive:
                    data = await reader.read(1024)
                    if data:
                        await session.broadcast_output(data)
                    else:
                        break
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug(f"Unix terminal reader error: {e}")
            finally:
                if self._sessions.get(session.session_id) is session:
                    self._sessions.pop(session.session_id, None)
                if session.websocket:
                    try:
                        await session.broadcast_output(
                            b"\r\n\r\n[Process completed]\r\n"
                        )
                    except Exception:
                        pass
                asyncio.create_task(session.terminate())

        session.reader_task = asyncio.create_task(_reader())

    async def handle_client_connection(
        self, websocket: WebSocket, session_id: str, shell_type: str
    ):
        """Attaches a WebSocket to a new or existing persistent session."""
        session = self._sessions.get(session_id)

        # If user switched shell profile on this session, terminate the old shell and respawn
        if session and session.is_alive and session.shell_type != shell_type:
            log.info(
                f"Switching shell for session '{session_id}': {session.shell_type} -> {shell_type}"
            )
            await session.terminate()
            session = None

        # 1. Spawn session if it doesn't exist or previous process died
        if not session or not session.is_alive:
            session = PersistentTerminalSession(session_id, shell_type)
            self._sessions[session_id] = session

            if platform.system() == "Windows":
                await self._spawn_windows_process(session)
            else:
                await self._spawn_unix_process(session)

        # 2. Attach WebSocket to this session
        session.websocket = websocket

        # 3. Replay scrollback buffer so user sees all previous command output
        for chunk in list(session.output_buffer):
            try:
                await websocket.send_bytes(chunk)
            except Exception:
                session.websocket = None
                return

        # 4. Handle incoming user typing or JSON resize control frames
        typed_chars = 0
        try:
            while session.is_alive:
                if platform.system() == "Windows":
                    message = await websocket.receive()
                    if message["type"] == "websocket.receive":
                        data = message.get("bytes") or message.get("text", "").encode(
                            "utf-8"
                        )
                        if data:
                            # Handle terminal resize messages from mobile client
                            if (
                                data.strip().startswith(b'{"type":')
                                and b'"resize"' in data
                            ):
                                try:
                                    cmd = json.loads(data.decode("utf-8"))
                                    if cmd.get("type") == "resize":
                                        session.set_size(
                                            cmd.get("cols", 80), cmd.get("rows", 24)
                                        )
                                        continue
                                except Exception:
                                    pass

                            is_backspace = data in (b"\x7f", b"\x08")
                            if is_backspace:
                                if typed_chars <= 0:
                                    continue
                                typed_chars -= 1
                                echo_data = b"\x08 \x08"
                            else:
                                if b"\r" in data or b"\n" in data:
                                    typed_chars = 0
                                    if b"\r" in data and b"\n" not in data:
                                        data = data.replace(b"\r", b"\r\n")
                                else:
                                    typed_chars += len(data.replace(b"\x1b", b""))
                                echo_data = data

                            if session.process and session.process.stdin:
                                session.process.stdin.write(data)
                                await session.process.stdin.drain()

                            try:
                                await websocket.send_bytes(echo_data)
                            except Exception:
                                pass
                    elif message["type"] == "websocket.disconnect":
                        break
                else:
                    data = await websocket.receive_bytes()
                    if data:
                        # Handle terminal resize messages from mobile client
                        if data.strip().startswith(b'{"type":') and b'"resize"' in data:
                            try:
                                cmd = json.loads(data.decode("utf-8"))
                                if cmd.get("type") == "resize":
                                    session.set_size(
                                        cmd.get("cols", 80), cmd.get("rows", 24)
                                    )
                                    continue
                            except Exception:
                                pass

                        if session.master_fd is not None:
                            os.write(session.master_fd, data)

        except (asyncio.CancelledError, WebSocketDisconnect):
            log.info(
                f"Client detached from persistent terminal session '{session_id}'. Shell remains active."
            )
        except Exception as e:
            log.debug(f"Terminal connection error on '{session_id}': {e}")
        finally:
            if session.websocket == websocket:
                session.websocket = None


terminal_service = TerminalService()

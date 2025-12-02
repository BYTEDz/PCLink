# src/pclink/api_server/terminal.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import platform
import subprocess
import sys
from typing import Any, Dict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

# Conditional import for PTY on non-Windows systems.
if platform.system() != "Windows":
    import pty
else:
    # Windows-specific imports for subprocess handling.
    import threading

from ..core.config import config_manager

log = logging.getLogger(__name__)


async def pipe_stream_to_websocket(stream: asyncio.StreamReader, websocket: WebSocket):
    """
    Reads data from an asyncio StreamReader and sends it over a WebSocket connection.

    Args:
        stream: The asyncio StreamReader to read data from.
        websocket: The WebSocket connection to send data to.
    """
    while not stream.at_eof():
        try:
            data = await stream.read(1024)
            if data:
                await websocket.send_bytes(data)
        except Exception:
            # Break the loop if any error occurs during reading or sending.
            break


async def handle_windows_terminal(websocket: WebSocket, shell_type: str = "cmd"):
    """
    Handles Windows terminal connections using subprocess with pipes.

    This function attempts to start the specified shell (cmd or powershell)
    and forwards data between the shell's stdin/stdout and the WebSocket.

    Args:
        websocket: The active WebSocket connection.
        shell_type: The type of shell to use ('cmd' or 'powershell').
    """
    log.info(f"Initializing Windows terminal with shell type: {shell_type}")

    # Determine the shell command and arguments.
    if shell_type.lower() == "powershell":
        shell_cmd = None
        # Prioritize PowerShell Core (pwsh), then fallback to Windows PowerShell.
        try:
            # Test availability of PowerShell Core.
            result = subprocess.run(["pwsh", "-Version"], capture_output=True, timeout=2)
            if result.returncode == 0:
                shell_cmd = ["pwsh", "-NoLogo", "-ExecutionPolicy", "Bypass"]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # pwsh not found or timed out.

        if not shell_cmd:
            try:
                # Fallback to Windows PowerShell.
                result = subprocess.run(
                    ["powershell", "-Command", "Get-Host"],
                    capture_output=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    shell_cmd = ["powershell", "-NoLogo", "-ExecutionPolicy", "Bypass"]
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass  # powershell not found or timed out.

        if not shell_cmd:
            # If neither PowerShell version is found, inform the client and close.
            await websocket.send_text("\r\n[PCLink Terminal Error] PowerShell not found on this system\r\n")
            await websocket.close(code=1011, reason="PowerShell not available")
            return
    else:
        # Default to Command Prompt (cmd).
        shell_cmd = ["cmd"]

    try:
        log.info(f"Starting subprocess: {' '.join(shell_cmd)}")
        # Use Popen for Windows compatibility; asyncio subprocess is not reliable.
        process = subprocess.Popen(
            shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr with stdout for simplicity.
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=False,  # Use binary mode for raw I/O.
            bufsize=0,  # Unbuffered I/O.
        )
        log.info(f"Subprocess started with PID: {process.pid}")

        # Send an initial connection message to the client.
        shell_name = "PowerShell" if shell_type.lower() == "powershell" else "Command Prompt"
        initial_msg = f"\r\n[PCLink Terminal] Connected to Windows {shell_name}\r\n"
        await websocket.send_text(initial_msg)
        log.debug(f"Sent initial message: {repr(initial_msg)}")

        loop = asyncio.get_event_loop()

        async def read_output():
            """Reads output from the subprocess and sends it to the WebSocket."""
            try:
                while process.poll() is None:
                    try:
                        # Read subprocess output in a separate thread to avoid blocking the event loop.
                        data = await loop.run_in_executor(
                            None,
                            lambda: process.stdout.read(512) if process.stdout else b"",
                        )
                        if data:
                            log.debug(f"Sending to client: {repr(data)}")
                            await websocket.send_bytes(data)
                        else:
                            # Short sleep if no data is immediately available to prevent tight looping.
                            await asyncio.sleep(0.05)  # Optimized: 20 iterations/sec instead of 100
                    except Exception as e:
                        log.error(f"Error reading subprocess output: {e}")
                        break
            except Exception as e:
                log.error(f"Output reader task error: {e}")

        async def write_input(data: bytes):
            """Writes data from the WebSocket to the subprocess's stdin."""
            try:
                if process.stdin and process.poll() is None:
                    await loop.run_in_executor(
                        None,
                        lambda: process.stdin.write(data) and process.stdin.flush(),
                    )
            except Exception as e:
                log.error(f"Error writing to subprocess stdin: {e}")

        # Start the task to continuously read output from the subprocess.
        output_task = asyncio.create_task(read_output())

        # Allow some time for the shell to initialize and potentially output banners.
        await asyncio.sleep(0.5)

        try:
            # Main loop to receive messages from the WebSocket and send them to the subprocess.
            while process.poll() is None:
                try:
                    # Receive data from the WebSocket.
                    message = await websocket.receive()

                    if message["type"] == "websocket.receive":
                        if "bytes" in message:
                            data = message["bytes"]
                        elif "text" in message:
                            data = message["text"].encode("utf-8")
                        else:
                            continue  # Ignore unexpected message types.

                        if data:
                            log.debug(f"Sending to terminal: {repr(data)}")
                            await write_input(data)

                except WebSocketDisconnect:
                    log.info("WebSocket disconnected by client.")
                    break
                except Exception as e:
                    log.error(f"Error processing WebSocket input: {e}")
                    break

        finally:
            # Cleanup resources upon disconnection or error.
            log.info("Cleaning up terminal session.")
            output_task.cancel()

            if process.poll() is None:
                try:
                    # Attempt graceful shutdown by sending the 'exit' command.
                    exit_cmd = b"exit\r\n"
                    await write_input(exit_cmd)

                    # Wait briefly for the process to exit cleanly.
                    for _ in range(30):  # Wait up to 3 seconds.
                        if process.poll() is not None:
                            break
                        await asyncio.sleep(0.1)

                    # Forcefully terminate if it's still running.
                    if process.poll() is None:
                        process.terminate()
                        await asyncio.sleep(0.5)  # Give it a moment to terminate.
                        if process.poll() is None:
                            process.kill()  # Force kill if termination failed.

                except ProcessLookupError:
                    pass  # Process already exited.
                except Exception as e:
                    log.error(f"Error during subprocess cleanup: {e}")
                    # Ensure the process is killed if any error occurs during graceful shutdown.
                    try:
                        process.kill()
                    except Exception:
                        pass

    except Exception as e:
        log.error(f"Terminal session error: {e}", exc_info=True)
        error_msg = f"\r\n[PCLink Terminal Error] Failed to start {shell_type}: {str(e)}\r\n"
        try:
            # Attempt to send the error message to the client.
            await websocket.send_text(error_msg)
        except Exception:
            pass  # Ignore errors if sending fails.
        try:
            # Close the WebSocket with an error code.
            await websocket.close(code=1011, reason=f"Terminal startup failed: {str(e)}")
        except Exception:
            pass


def create_terminal_router(api_key: str) -> APIRouter:
    """
    Creates an APIRouter for the Terminal API endpoints.

    Args:
        api_key: The server's main API key for authentication.

    Returns:
        An configured APIRouter instance.
    """
    router = APIRouter()

    @router.get("/shells")
    async def get_available_shells(token: str = Query(None)):
        """
        Retrieves a list of available shells for the current platform.

        Args:
            token: The API key for authentication.

        Returns:
            A JSON object containing a list of available shells and the default shell,
            or an error message if authentication fails.
        """
        if not token:
            return {"error": "Missing API Key"}

        authenticated = False
        try:
            # Attempt to validate against the server's main API key.
            from ..core.validators import validate_api_key
            if validate_api_key(token) == api_key:
                authenticated = True
        except ImportError:
            log.warning("Could not import validator module.")
        except Exception as e:
            log.warning(f"Error validating server API key: {e}")

        if not authenticated:
            try:
                # If server API key validation fails, try validating against device API keys.
                from ..core.device_manager import device_manager
                device = device_manager.get_device_by_api_key(token)
                if device and device.is_approved:
                    authenticated = True
                    device_manager.update_device_last_seen(device.device_id)
            except ImportError:
                log.warning("Could not import device_manager module.")
            except Exception as e:
                log.warning(f"Error validating device API key: {e}")

        if not authenticated:
            return {"error": "Invalid API Key"}

        # Platform-specific shell detection.
        if platform.system() == "Windows":
            shells = ["cmd"]
            # Check for Windows PowerShell availability.
            try:
                result = subprocess.run(
                    ["powershell", "-Command", "Get-Host"],
                    capture_output=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    shells.append("powershell")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            # Check for PowerShell Core (pwsh) availability.
            try:
                result = subprocess.run(["pwsh", "-Version"], capture_output=True, timeout=2)
                if result.returncode == 0 and "powershell" not in shells:
                    # Add 'powershell' if pwsh is found, as it will be used for the 'powershell' type.
                    shells.append("powershell")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            return {"shells": shells, "default": "cmd"}
        else:
            # Unix/Linux shell detection.
            available_shells = []
            common_shells = ["bash", "sh", "zsh", "fish"]

            for shell in common_shells:
                try:
                    # Use 'which' to find the executable path for the shell.
                    subprocess.run(["which", shell], capture_output=True, timeout=2)
                    available_shells.append(shell)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass  # Shell not found.

            # Determine the default shell from the SHELL environment variable.
            default_shell = os.environ.get("SHELL", "bash").split("/")[-1]
            return {"shells": available_shells, "default": default_shell}

    @router.websocket("/ws")
    async def terminal_websocket(websocket: WebSocket, token: str = Query(None)):
        """
        WebSocket endpoint for establishing terminal sessions.

        Args:
            websocket: The incoming WebSocket connection.
            token: The API key for authentication.
        """
        if not token:
            await websocket.close(code=1008, reason="Missing API Key")
            return

        # Authenticate the client using API key.
        authenticated = False
        try:
            from ..core.validators import validate_api_key
            if validate_api_key(token) == api_key:
                authenticated = True
        except ImportError:
            log.warning("Could not import validator module.")
        except Exception as e:
            log.warning(f"Error validating server API key: {e}")

        if not authenticated:
            try:
                from ..core.device_manager import device_manager
                device = device_manager.get_device_by_api_key(token)
                if device and device.is_approved:
                    authenticated = True
                    device_manager.update_device_last_seen(device.device_id)
            except ImportError:
                log.warning("Could not import device_manager module.")
            except Exception as e:
                log.warning(f"Error validating device API key: {e}")

        if not authenticated:
            log.warning("Terminal WebSocket connection rejected: Invalid API Key.")
            await websocket.close(code=1008, reason="Invalid API Key")
            return

        # Check if terminal access is enabled
        terminal_access_enabled = config_manager.get("allow_terminal_access", False)
        log.info(f"Terminal access check: allow_terminal_access={terminal_access_enabled}")
        if not terminal_access_enabled:
            log.warning("Terminal WebSocket connection rejected: Terminal access is disabled.")
            await websocket.close(
                code=4002, reason="Terminal access is disabled by server policy."
            )
            return

        await websocket.accept()
        log.info(f"Terminal WebSocket connection accepted from {websocket.client}.")

        # Handle Windows terminal connections.
        if platform.system() == "Windows":
            # Determine the shell type from query parameters, defaulting to 'cmd'.
            shell_type = websocket.query_params.get("shell", "cmd").lower()
            if shell_type not in ["cmd", "powershell"]:
                shell_type = "cmd"  # Fallback to cmd if an unsupported type is requested.

            log.info(f"Starting Windows terminal session with shell: {shell_type}")
            await handle_windows_terminal(websocket, shell_type)
            return

        # Handle Unix/Linux terminal connections using PTY.
        shell_cmd = os.environ.get("SHELL", "bash")
        try:
            # Open a pseudo-terminal pair.
            master_fd, slave_fd = pty.openpty()

            # Start the shell process, redirecting its stdio to the slave PTY.
            process = await asyncio.create_subprocess_exec(
                shell_cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,  # Make the process a session leader.
            )
            os.close(slave_fd)  # Close the slave file descriptor in the parent process.

            loop = asyncio.get_running_loop()
            # Create an StreamReader to read from the master PTY descriptor.
            pty_reader_stream = asyncio.StreamReader(loop=loop)
            protocol = asyncio.StreamReaderProtocol(pty_reader_stream)
            await loop.connect_read_pipe(lambda: protocol, os.fdopen(master_fd, "rb", 0))

            # Task to forward data from the PTY to the WebSocket.
            forward_task = asyncio.create_task(
                pipe_stream_to_websocket(pty_reader_stream, websocket)
            )

            # Main loop to receive data from WebSocket and write to the PTY.
            while process.returncode is None:
                data = await websocket.receive_bytes()
                os.write(master_fd, data)
        except WebSocketDisconnect:
            log.info("Terminal WebSocket disconnected by client.")
        except ProcessLookupError:
            log.warning("Terminal process not found during operation.")
        except Exception as e:
            log.error(f"Error in Unix/Linux terminal session: {e}", exc_info=True)
            try:
                await websocket.send_text(f"[PCLink Terminal Error] {e}\r\n")
            except Exception:
                pass
        finally:
            # Cleanup resources.
            if "forward_task" in locals() and not forward_task.done():
                forward_task.cancel()
            if process and process.returncode is None:
                try:
                    process.terminate()
                    await process.wait()
                except ProcessLookupError:
                    pass  # Process already ended.
            if "master_fd" in locals() and master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass  # File descriptor might already be closed.
            try:
                await websocket.close()
            except Exception:
                pass  # Ignore errors during final close.

    return router
"""
PCLink - Remote PC Control Server - Terminal API Module
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

Terminal API provides WebSocket-based terminal access for both Unix and Windows systems.

Windows Support:
- Command Prompt (cmd): Default Windows shell
- PowerShell: Both Windows PowerShell and PowerShell Core supported
- Uses subprocess with pipes instead of PTY for Windows compatibility

Unix/Linux Support:
- Uses PTY (pseudo-terminal) for full terminal emulation
- Supports bash, sh, zsh, fish, and other common shells

Usage:
- GET /terminal/shells - List available shells for the platform
- WebSocket /terminal/ws?token=<api_key>&shell=<shell_type> - Connect to terminal
"""

import asyncio
import logging
import os
import platform
import subprocess
import sys

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

if platform.system() != "Windows":
    import pty
else:
    # Windows-specific imports for subprocess handling
    import threading

log = logging.getLogger(__name__)


async def pipe_stream_to_websocket(stream, websocket: WebSocket):
    while not stream.at_eof():
        try:
            data = await stream.read(1024)
            if data:
                await websocket.send_bytes(data)
        except Exception:
            break


async def handle_windows_terminal(websocket: WebSocket, shell_type: str = "cmd"):
    """Handle Windows terminal using subprocess with pipes."""
    log.info(f"Initializing Windows terminal with shell type: {shell_type}")
    
    # Determine shell command and arguments
    if shell_type.lower() == "powershell":
        # Try PowerShell Core first, then Windows PowerShell
        shell_cmd = None
        try:
            # Test if PowerShell Core is available
            result = subprocess.run(["pwsh", "-Version"], capture_output=True, timeout=2)
            if result.returncode == 0:
                shell_cmd = ["pwsh", "-NoLogo", "-ExecutionPolicy", "Bypass"]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        if not shell_cmd:
            try:
                # Fall back to Windows PowerShell
                result = subprocess.run(["powershell", "-Command", "Get-Host"], 
                                      capture_output=True, timeout=2)
                if result.returncode == 0:
                    shell_cmd = ["powershell", "-NoLogo", "-ExecutionPolicy", "Bypass"]
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        
        if not shell_cmd:
            await websocket.send_text("\r\n[PCLink Terminal Error] PowerShell not found on this system\r\n")
            await websocket.close(code=1011, reason="PowerShell not available")
            return
    else:
        # Default to cmd
        shell_cmd = ["cmd"]  # Remove /Q flag to see if it helps

    try:
        # Use Popen for Windows compatibility (asyncio subprocess doesn't work on Windows)
        log.info(f"Starting subprocess: {' '.join(shell_cmd)}")
        process = subprocess.Popen(
            shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr with stdout
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            text=False,  # Use binary mode
            bufsize=0    # Unbuffered
        )
        log.info(f"Subprocess started with PID: {process.pid}")

        # Send initial connection message
        shell_name = "PowerShell" if shell_type.lower() == "powershell" else "Command Prompt"
        initial_msg = f"\r\n[PCLink Terminal] Connected to Windows {shell_name}\r\n"
        await websocket.send_text(initial_msg)
        log.info(f"Sent initial message: {repr(initial_msg)}")
        
        # Create async wrappers for subprocess I/O using thread executor
        loop = asyncio.get_event_loop()
        
        async def read_output():
            """Read output from process and send to websocket."""
            try:
                while process.poll() is None:
                    try:
                        # Read from subprocess in a thread to avoid blocking
                        data = await loop.run_in_executor(
                            None, 
                            lambda: process.stdout.read(512) if process.stdout else b''
                        )
                        if data:
                            log.debug(f"Sending to client: {repr(data)}")
                            await websocket.send_bytes(data)
                        else:
                            await asyncio.sleep(0.01)  # Small delay if no data
                    except Exception as e:
                        log.error(f"Error reading output: {e}")
                        break
            except Exception as e:
                log.error(f"Output reader error: {e}")

        async def write_input(data):
            """Write input to process stdin."""
            try:
                if process.stdin and process.poll() is None:
                    await loop.run_in_executor(
                        None,
                        lambda: process.stdin.write(data) and process.stdin.flush()
                    )
            except Exception as e:
                log.error(f"Error writing input: {e}")

        # Start output reading task
        output_task = asyncio.create_task(read_output())
        
        # Wait a moment for initial output
        await asyncio.sleep(0.5)

        try:
            # Handle input from websocket
            while process.poll() is None:
                try:
                    # Receive data from websocket
                    message = await websocket.receive()
                    
                    if message["type"] == "websocket.receive":
                        if "bytes" in message:
                            data = message["bytes"]
                        elif "text" in message:
                            data = message["text"].encode("utf-8")
                        else:
                            continue
                        
                        if data:
                            log.debug(f"Sending to terminal: {repr(data)}")
                            await write_input(data)
                            
                except WebSocketDisconnect:
                    log.info("WebSocket disconnected by client")
                    break
                except Exception as e:
                    log.error(f"Error in terminal input loop: {e}")
                    break

        finally:
            # Cleanup
            log.info("Cleaning up terminal session")
            output_task.cancel()
            
            if process.poll() is None:
                try:
                    # Try graceful termination first
                    exit_cmd = b"exit\r\n"
                    await write_input(exit_cmd)
                    
                    # Wait for graceful exit
                    for _ in range(30):  # Wait up to 3 seconds
                        if process.poll() is not None:
                            break
                        await asyncio.sleep(0.1)
                    
                    # Force termination if still running
                    if process.poll() is None:
                        process.terminate()
                        await asyncio.sleep(0.5)
                        if process.poll() is None:
                            process.kill()
                            
                except Exception as e:
                    log.error(f"Error during cleanup: {e}")
                    try:
                        process.kill()
                    except:
                        pass

    except Exception as e:
        log.error(f"Terminal session error: {e}", exc_info=True)
        error_msg = f"\r\n[PCLink Terminal Error] Failed to start {shell_type}: {str(e)}\r\n"
        try:
            await websocket.send_text(error_msg)
        except:
            pass
        try:
            await websocket.close(code=1011, reason=f"Terminal startup failed: {str(e)}")
        except:
            pass


def create_terminal_router(api_key: str, allow_insecure_shell: bool) -> APIRouter:
    router = APIRouter()

    @router.get("/shells")
    async def get_available_shells(token: str = Query(None)):
        """Get list of available shells for the current platform."""
        if not token:
            return {"error": "Missing API Key"}
        
        # Check authentication (both server API key and device API keys)
        authenticated = False
        try:
            from ..core.validators import validate_api_key
            if validate_api_key(token) == api_key:
                authenticated = True
        except:
            pass
        
        if not authenticated:
            # Check device API keys
            try:
                from ..core.device_manager import device_manager
                device = device_manager.get_device_by_api_key(token)
                if device and device.is_approved:
                    authenticated = True
                    device_manager.update_device_last_seen(device.device_id)
            except:
                pass
        
        if not authenticated:
            return {"error": "Invalid API Key"}
        
        if platform.system() == "Windows":
            shells = ["cmd"]
            # Check if PowerShell is available
            try:
                result = subprocess.run(["powershell", "-Command", "Get-Host"], 
                                      capture_output=True, timeout=2)
                if result.returncode == 0:
                    shells.append("powershell")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            
            # Check if PowerShell Core is available
            try:
                result = subprocess.run(["pwsh", "-Version"], capture_output=True, timeout=2)
                if result.returncode == 0 and "powershell" not in shells:
                    shells.append("powershell")  # PowerShell Core will be used
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            
            return {"shells": shells, "default": "cmd"}
        else:
            # Unix/Linux shells
            available_shells = []
            common_shells = ["bash", "sh", "zsh", "fish"]
            
            for shell in common_shells:
                try:
                    subprocess.run(["which", shell], capture_output=True, timeout=2)
                    available_shells.append(shell)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
            
            default_shell = os.environ.get("SHELL", "bash").split("/")[-1]
            return {"shells": available_shells, "default": default_shell}

    @router.websocket("/ws")
    async def terminal_websocket(websocket: WebSocket, token: str = Query(None)):
        if not token:
            await websocket.close(code=1008, reason="Missing API Key")
            return
        
        # Check authentication (both server API key and device API keys)
        authenticated = False
        try:
            from ..core.validators import validate_api_key
            if validate_api_key(token) == api_key:
                authenticated = True
        except:
            pass
        
        if not authenticated:
            # Check device API keys
            try:
                from ..core.device_manager import device_manager
                device = device_manager.get_device_by_api_key(token)
                if device and device.is_approved:
                    authenticated = True
                    device_manager.update_device_last_seen(device.device_id)
            except:
                pass
        
        if not authenticated:
            log.warning("Terminal WebSocket connection rejected: Invalid API Key")
            await websocket.close(code=1008, reason="Invalid API Key")
            return

        is_secure_scheme = websocket.scope.get("scheme") in ("https", "wss")
        if not is_secure_scheme and not allow_insecure_shell:
            log.warning("Terminal WebSocket connection rejected: Insecure terminal disabled")
            await websocket.close(
                code=4001, reason="Insecure terminal is disabled by server policy."
            )
            return

        await websocket.accept()
        log.info(f"Terminal WebSocket connection accepted from {websocket.client}")

        if platform.system() == "Windows":
            # Get shell type from query parameter (default to cmd)
            shell_type = websocket.query_params.get("shell", "cmd").lower()
            if shell_type not in ["cmd", "powershell"]:
                shell_type = "cmd"
            
            log.info(f"Starting Windows terminal session with shell: {shell_type}")
            await handle_windows_terminal(websocket, shell_type)
            return

        # Unix/Linux terminal handling (existing code)
        shell_cmd = os.environ.get("SHELL", "bash")
        master_fd, slave_fd = pty.openpty()

        process = await asyncio.create_subprocess_exec(
            shell_cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)

        loop = asyncio.get_running_loop()

        pty_reader_stream = asyncio.StreamReader(loop=loop)
        protocol = asyncio.StreamReaderProtocol(pty_reader_stream)
        await loop.connect_read_pipe(lambda: protocol, os.fdopen(master_fd, "rb", 0))

        forward_task = asyncio.create_task(
            pipe_stream_to_websocket(pty_reader_stream, websocket)
        )

        try:
            while process.returncode is None:
                data = await websocket.receive_bytes()
                os.write(master_fd, data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            forward_task.cancel()
            if process.returncode is None:
                try:
                    process.terminate()
                    await process.wait()
                except ProcessLookupError:
                    pass
            os.close(master_fd)

    return router

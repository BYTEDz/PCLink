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
"""

import asyncio
import os
import platform

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

if platform.system() != "Windows":
    import pty


async def pipe_stream_to_websocket(stream, websocket: WebSocket):
    while not stream.at_eof():
        try:
            data = await stream.read(1024)
            if data:
                await websocket.send_bytes(data)
        except Exception:
            break


def create_terminal_router(api_key: str, allow_insecure_shell: bool) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def terminal_websocket(websocket: WebSocket, token: str = Query(None)):
        if not token or token != api_key:
            await websocket.close(code=1008, reason="Invalid or Missing API Key")
            return

        is_secure_scheme = websocket.scope.get("scheme") in ("https", "wss")
        if not is_secure_scheme and not allow_insecure_shell:
            await websocket.close(
                code=4001, reason="Insecure terminal is disabled by server policy."
            )
            return

        await websocket.accept()

        if platform.system() == "Windows":
            await websocket.send_text(
                "\r\n[PCLink Server]: Terminal feature is not supported on Windows hosts.\r\nConnection will be closed.\r\n"
            )
            await websocket.close(code=1000)
            return

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

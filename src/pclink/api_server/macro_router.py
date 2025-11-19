# src/pclink/api_server/macro_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import asyncio
from typing import Any, Dict, List, Coroutine, Literal, Optional
import io
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .applications_router import launch_application as launch_app_from_router, AppLaunchPayload

try:
    import pefile
    from PIL import Image
    ICON_EXTRACTION_SUPPORTED = True
except ImportError:
    ICON_EXTRACTION_SUPPORTED = False

from .system_router import power_command, set_volume
from .input_router import send_keyboard_input, KeyboardInputModel
from .utils_router import run_command, CommandModel, set_clipboard, ClipboardModel
from .file_browser import open_file_on_server, PathPayload
from .media_router import media_command

log = logging.getLogger(__name__)
router = APIRouter()

class Action(BaseModel):
    type: str = Field(..., description="The type of action to perform.")
    payload: Dict[str, Any] = Field({}, description="Parameters for the action.")
class Macro(BaseModel):
    name: str = "Unnamed Macro"
    actions: List[Action]
class ParameterOption(BaseModel):
    name_key: str = Field(...)
    value: str = Field(...)
class ParameterDefinition(BaseModel):
    name: str = Field(...)
    label_key: Optional[str] = Field(None)
    type: Literal["string", "select", "hidden", "multiselect"] = Field(...)
    required: bool = True
    options: List[ParameterOption] = Field([])
    default_value: Optional[Any] = Field(None)
class ActionDefinition(BaseModel):
    type: str = Field(...)
    name_key: str = Field(...)
    description_key: str = Field(...)
    icon: str = Field(...)
    parameters: List[ParameterDefinition] = []

AVAILABLE_ACTIONS: List[ActionDefinition] = [
    ActionDefinition(type="launch_app", name_key="action_type_launch_app", description_key="action_desc_launch_app", icon="rocket_launch", parameters=[ParameterDefinition(name="command", label_key="app_to_launch_label", type="string"), ParameterDefinition(name="app_name", label_key="app_name_label", type="string", required=False)]),
    ActionDefinition(type="power", name_key="action_type_power", description_key="action_desc_power", icon="power_settings_new", parameters=[ParameterDefinition(name="command", label_key="power_action_label", type="select", options=[ParameterOption(name_key="power_action_shutdown", value="shutdown"), ParameterOption(name_key="power_action_reboot", value="reboot"), ParameterOption(name_key="power_action_sleep", value="sleep"), ParameterOption(name_key="power_action_lock", value="lock"), ParameterOption(name_key="power_action_logout", value="logout")])]),
    ActionDefinition(type="media", name_key="action_type_media", description_key="action_desc_media", icon="play_circle_filled", parameters=[ParameterDefinition(name="action", label_key="media_action_label", type="select", options=[ParameterOption(name_key="media_action_play_pause", value="play_pause"), ParameterOption(name_key="media_action_next", value="next"), ParameterOption(name_key="media_action_previous", value="previous"), ParameterOption(name_key="media_action_stop", value="stop")])]),
    ActionDefinition(type="volume", name_key="action_type_volume", description_key="action_desc_volume", icon="volume_up", parameters=[ParameterDefinition(name="level", label_key="volume_level_label", type="string")]),
    ActionDefinition(type="delay", name_key="action_type_delay", description_key="action_desc_delay", icon="timer", parameters=[ParameterDefinition(name="duration_ms", label_key="duration_ms_label", type="string")]),
    ActionDefinition(type="command", name_key="action_type_command", description_key="action_desc_command", icon="terminal", parameters=[ParameterDefinition(name="command", label_key="command_label", type="string")]),
    ActionDefinition(type="input_text", name_key="action_type_input_text", description_key="action_desc_input_text", icon="keyboard", parameters=[ParameterDefinition(name="text", label_key="text_to_type_label", type="string")]),
    ActionDefinition(
        type="input_keys",
        name_key="action_type_input_keys",
        description_key="action_desc_input_keys",
        icon="keyboard_command_key",
        parameters=[
            ParameterDefinition(name="key", label_key="key_label", type="string"),
            ParameterDefinition(
                name="modifiers",
                label_key="modifiers_label",
                type="multiselect",
                required=False,
                options=[
                    ParameterOption(name_key="modifier_ctrl", value="ctrl"),
                    ParameterOption(name_key="modifier_alt", value="alt"),
                    ParameterOption(name_key="modifier_shift", value="shift"),
                    ParameterOption(name_key="modifier_win_meta", value="meta"),
                ]
            )
        ]
    ),
    ActionDefinition(type="clipboard", name_key="action_type_clipboard", description_key="action_desc_clipboard", icon="content_paste", parameters=[ParameterDefinition(name="text", label_key="clipboard_text_label", type="string")]),
    ActionDefinition(type="notification", name_key="action_type_notification", description_key="action_desc_notification", icon="notifications", parameters=[ParameterDefinition(name="title", label_key="notification_title_label", type="string"), ParameterDefinition(name="message", label_key="notification_message_label", type="string", required=False)]),
    ActionDefinition(type="file", name_key="action_type_open_file", description_key="action_desc_open_file", icon="folder_open", parameters=[ParameterDefinition(name="path", label_key="path_label", type="string")]),
]

async def handle_launch_app_action(payload: Dict[str, Any]):
    command = payload.get("command")
    if not command: raise ValueError("Missing 'command' for launch_app action.")
    await launch_app_from_router(AppLaunchPayload(command=command))

async def handle_delay_action(payload: Dict[str, Any]):
    duration_str = payload.get('duration_ms')
    if not duration_str: raise ValueError("Missing 'duration_ms'.")
    try:
        duration_ms = int(duration_str)
        if duration_ms <= 0: raise ValueError("Duration must be a positive number.")
        await asyncio.sleep(duration_ms / 1000.0)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid duration: '{duration_str}'. Must be a positive integer.")

async def handle_power_action(payload: Dict[str, Any]):
    command = payload.get("command")
    if not command: raise ValueError("Missing 'command'.")
    await power_command(command)

async def handle_media_action(payload: Dict[str, Any]):
    action = payload.get("action")
    if not action: raise ValueError("Missing 'action'.")
    await media_command({"action": action})

async def handle_volume_action(payload: Dict[str, Any]):
    level_str = payload.get("level")
    if level_str is None: raise ValueError("Missing 'level'.")
    try:
        level = int(level_str)
        if not 0 <= level <= 100: raise ValueError("Volume must be between 0 and 100.")
        await set_volume(level)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid volume: '{level_str}'. Must be an integer between 0 and 100.")

async def handle_input_text_action(payload: Dict[str, Any]):
    text = payload.get('text')
    if text is None: raise ValueError("Missing 'text'.")
    await send_keyboard_input(KeyboardInputModel(text=text))

async def handle_input_keys_action(payload: Dict[str, Any]):
    key = payload.get('key')
    if not key: raise ValueError("Missing 'key'.")
    modifiers = payload.get('modifiers', [])
    if not isinstance(modifiers, list):
        raise ValueError("Modifiers must be a list of strings.")
    await send_keyboard_input(KeyboardInputModel(key=key, modifiers=modifiers))

async def handle_clipboard_action(payload: Dict[str, Any]):
    text = payload.get("text")
    if text is None: raise ValueError("Missing 'text'.")
    await set_clipboard(ClipboardModel(text=text))

async def handle_notification_action(request: Request, payload: Dict[str, Any]):
    title = payload.get("title")
    if not title: raise ValueError("Missing 'title'.")
    message = payload.get("message", "")
    final_message = message if message else " "
    tray_manager = getattr(request.app.state, 'tray_manager', None)
    if tray_manager:
        tray_manager.show_notification(title, final_message)
    else:
        log.warning("Could not show notification: Tray manager not available.")

async def handle_command_action(payload: Dict[str, Any]):
    command_str = payload.get('command')
    if not command_str: raise ValueError("Missing 'command'.")
    await run_command(CommandModel(command=command_str))

async def handle_file_action(payload: Dict[str, Any]):
    path_str = payload.get('path')
    if not path_str: raise ValueError("Missing 'path'.")
    await open_file_on_server(PathPayload(path=path_str))

@router.get("/available-actions", response_model=List[ActionDefinition], summary="Get all available macro actions")
async def get_available_actions():
    return sorted(AVAILABLE_ACTIONS, key=lambda x: x.name_key)

@router.post("/execute", summary="Execute a macro")
async def execute_macro(request: Request, macro: Macro):
    ACTION_HANDLERS = {
        "launch_app": handle_launch_app_action,
        "power": handle_power_action,
        "media": handle_media_action,
        "volume": handle_volume_action,
        "delay": handle_delay_action,
        "command": handle_command_action,
        "input_text": handle_input_text_action,
        "input_keys": handle_input_keys_action,
        "clipboard": handle_clipboard_action,
        "notification": handle_notification_action,
        "file": handle_file_action,
    }
    log.info(f"Executing macro '{macro.name}' with {len(macro.actions)} actions.")
    for i, action in enumerate(macro.actions):
        log.info(f"Executing action {i+1}/{len(macro.actions)}: type='{action.type}'")
        handler = ACTION_HANDLERS.get(action.type)
        if not handler:
            log.error(f"Macro failed: No handler for action '{action.type}'.")
            raise HTTPException(status_code=400, detail=f"Action {i+1}: Unknown type '{action.type}'.")
        try:
            if action.type == "notification":
                await handler(request, action.payload)
            else:
                await handler(action.payload)
        except ValueError as ve:
            log.error(f"Macro failed with invalid payload for '{action.type}': {ve}")
            raise HTTPException(status_code=400, detail=f"Action {i+1} ('{action.type}'): Invalid payload. {ve}")
        except Exception as e:
            log.error(f"Macro failed during execution of '{action.type}': {e}")
            raise HTTPException(status_code=500, detail=f"Action {i+1} ('{action.type}') failed. Reason: {str(e)}")
    log.info(f"Successfully executed macro '{macro.name}'.")
    return {"status": "success", "message": f"Macro '{macro.name}' executed successfully."}
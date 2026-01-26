# src/pclink/api_server/macro_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services.macro_service import macro_service

log = logging.getLogger(__name__)
router = APIRouter()

class Action(BaseModel):
    type: str; payload: Dict[str, Any] = {}

class Macro(BaseModel):
    name: str = "Unnamed Macro"; actions: List[Action]

class ParameterOption(BaseModel): name_key: str; value: str

class ParameterDefinition(BaseModel):
    name: str; label_key: Optional[str] = None
    type: Literal["string", "select", "hidden", "multiselect"]
    required: bool = True; options: List[ParameterOption] = []; default_value: Optional[Any] = None

class ActionDefinition(BaseModel):
    type: str; name_key: str; description_key: str; icon: str; parameters: List[ParameterDefinition] = []

AVAILABLE_ACTIONS = [
    ActionDefinition(type="launch_app", name_key="action_type_launch_app", description_key="action_desc_launch_app", icon="rocket_launch", parameters=[ParameterDefinition(name="command", label_key="app_to_launch_label", type="string")]),
    ActionDefinition(type="power", name_key="action_type_power", description_key="action_desc_power", icon="power_settings_new", parameters=[ParameterDefinition(name="command", label_key="power_action_label", type="select", options=[ParameterOption(name_key="power_action_shutdown", value="shutdown"), ParameterOption(name_key="power_action_reboot", value="reboot"), ParameterOption(name_key="power_action_sleep", value="sleep"), ParameterOption(name_key="power_action_lock", value="lock"), ParameterOption(name_key="power_action_logout", value="logout")])]),
    ActionDefinition(type="media", name_key="action_type_media", description_key="action_desc_media", icon="play_circle_filled", parameters=[ParameterDefinition(name="action", label_key="media_action_label", type="select", options=[ParameterOption(name_key="media_action_play_pause", value="play_pause"), ParameterOption(name_key="media_action_next", value="next"), ParameterOption(name_key="media_action_previous", value="previous")])]),
    ActionDefinition(type="volume", name_key="action_type_volume", description_key="action_desc_volume", icon="volume_up", parameters=[ParameterDefinition(name="level", label_key="volume_level_label", type="string")]),
    ActionDefinition(type="delay", name_key="action_type_delay", description_key="action_desc_delay", icon="timer", parameters=[ParameterDefinition(name="duration_ms", label_key="duration_ms_label", type="string")]),
    ActionDefinition(type="command", name_key="action_type_command", description_key="action_desc_command", icon="terminal", parameters=[ParameterDefinition(name="command", label_key="command_label", type="string")]),
    ActionDefinition(type="input_text", name_key="action_type_input_text", description_key="action_desc_input_text", icon="keyboard", parameters=[ParameterDefinition(name="text", label_key="text_to_type_label", type="string")]),
    ActionDefinition(type="input_keys", name_key="action_type_input_keys", description_key="action_desc_input_keys", icon="keyboard_command_key", parameters=[ParameterDefinition(name="key", label_key="key_label", type="string")]),
    ActionDefinition(type="clipboard", name_key="action_type_clipboard", description_key="action_desc_clipboard", icon="content_paste", parameters=[ParameterDefinition(name="text", label_key="clipboard_text_label", type="string")]),
    ActionDefinition(type="notification", name_key="action_type_notification", description_key="action_desc_notification", icon="notifications", parameters=[ParameterDefinition(name="title", label_key="notification_title_label", type="string"), ParameterDefinition(name="message", label_key="notification_message_label", type="string", required=False)]),
    ActionDefinition(type="file", name_key="action_type_open_file", description_key="action_desc_open_file", icon="folder_open", parameters=[ParameterDefinition(name="path", label_key="path_label", type="string")]),
]

@router.get("/available-actions", response_model=List[ActionDefinition])
async def get_available_actions():
    return sorted(AVAILABLE_ACTIONS, key=lambda x: x.name_key)

@router.post("/execute")
async def execute_macro(request: Request, macro: Macro):
    # Sync notification handler from app state to service
    tray_manager = getattr(request.app.state, 'tray_manager', None)
    if tray_manager:
        macro_service.set_notification_handler(tray_manager.show_notification)
    
    try:
        await macro_service.execute_macro(macro.name, [a.model_dump() for a in macro.actions])
        return {"status": "success"}
    except Exception as e:
        log.error(f"Macro failed: {e}")
        raise HTTPException(500, detail=str(e))
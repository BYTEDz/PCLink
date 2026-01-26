# src/pclink/api_server/services.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
Compatibility layer for the old services location. 
All logic has been moved to src/pclink/services/
"""

from ..services import system_service, media_service, input_service

# For backward compatibility with existing imports
NetworkMonitor = system_service._network_monitor.__class__

async def get_system_info_data(network_monitor=None):
    return await system_service.get_system_info()

async def get_media_info_data():
    return await media_service.get_media_info()

# Input controls
mouse_controller = input_service.mouse
keyboard_controller = input_service.keyboard
button_map = getattr(input_service, 'button_map', {})
get_key = getattr(input_service, 'keyboard_press_key', lambda k: k) # Simple fallback

PYNPUT_AVAILABLE = input_service.mouse is not None

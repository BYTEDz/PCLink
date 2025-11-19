# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import threading
from typing import Dict, Any, Callable, List

# A thread-safe global store for connected devices.
# The structure is { "ip_address": {"last_seen": timestamp, "name": "Device Name"} }
connected_devices = {}
_device_lock = threading.RLock()

# Legacy Qt callback system removed - using WebSocket notifications only


# Controller reference for API access
controller = None

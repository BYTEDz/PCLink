# filepath: src/pclink/cli/helpers.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click
import requests

from ..core import constants
from ..core.config import config_manager

try:
    from prettytable import PrettyTable
except ImportError:
    PrettyTable = None

_ = gettext.gettext

CONTROL_API_URL = f"http://127.0.0.1:{constants.CONTROL_PORT}"


def _wait_for_condition(condition, timeout=5, interval=1):
    """Wait for a condition to be met within a timeout."""
    for _ in range(timeout):
        if condition():
            return True
        time.sleep(interval)
    return False


def is_server_running():
    """Checks if the internal control API is reachable."""
    try:
        response = requests.get(f"{CONTROL_API_URL}/status", timeout=0.5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _api_call(method, url, **kwargs):
    """Helper for CLI API calls using IPv4 loopback."""
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        res = requests.request(
            method,
            url,
            verify=False,
            headers={"X-Internal-Auth": "true"},
            timeout=5,
            **kwargs,
        )
        if method == "GET":
            return res.json() if res.status_code == 200 else None
        return res.status_code == 200
    except Exception:
        return None if method == "GET" else False


def _get_api_data(url: str, params=None):
    return _api_call("GET", url, params=params)


def _post_api_data(url: str, params=None, json=None):
    return _api_call("POST", url, params=params, json=json)


def _print_table(headers, rows, widths):
    """Unified table printer with PrettyTable fallback."""
    if PrettyTable:
        table = PrettyTable()
        table.field_names = headers
        table.align = "l"
        for row in rows:
            table.add_row(row)
        click.echo(table)
    else:
        fmt = " | ".join([f"{{{i}:<{w}}}" for i, w in enumerate(widths)])
        click.secho(fmt.format(*headers), bold=True)
        click.echo("-" * (sum(widths) + len(widths) * 3 - 3))
        for row in rows:
            click.echo(fmt.format(*[str(x) for x in row]))


def _resolve_target_id(id_or_idx, api_endpoint, list_key, id_key="id"):
    """Resolve an index to an ID via API data if applicable."""
    if not str(id_or_idx).isdigit():
        return id_or_idx

    port = config_manager.get("server_port", 38080)
    data = (
        _get_api_data(f"https://127.0.0.1:{port}/ui/{api_endpoint}")
        if is_server_running()
        else None
    )

    if data and list_key in data:
        items = data[list_key]
        idx = int(id_or_idx) - 1
        if isinstance(items, dict):  # For blacklist dictionaries
            keys = list(items.keys())
            if 0 <= idx < len(keys):
                return keys[idx]
        elif isinstance(items, list):  # For regular device lists
            if 0 <= idx < len(items):
                return items[idx][id_key]
    return id_or_idx


def _start_server_process():
    """Launches the main PCLink process in a fully detached state."""
    try:
        # Resolve the root package directory to locate launcher.py properly
        root_dir = Path(__file__).resolve().parent.parent
        launcher_path = os.path.join(root_dir, "launcher.py")

        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }

        executable = sys.executable
        if sys.platform == "win32":
            if not getattr(sys, "frozen", False):
                pythonw = Path(executable).parent / "pythonw.exe"
                if pythonw.exists():
                    executable = str(pythonw)

            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | 0x08000000
            )
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen([executable, launcher_path], **kwargs)

        click.secho(_("Awaiting PCLink daemon initialization..."), fg="cyan")
        return _wait_for_condition(is_server_running, 5)
    except Exception as e:
        click.secho(
            _("Failed to initialize PCLink daemon: {}").format(e),
            fg="red",
            bold=True,
            err=True,
        )
        return False


def _open_browser():
    """Opens the PCLink Web UI in the default browser."""
    if not is_server_running():
        click.secho(
            _("Cannot launch Web UI; PCLink daemon is offline."), fg="red", err=True
        )
        return

    try:
        response = requests.get(f"{CONTROL_API_URL}/web-url", timeout=1)
        response.raise_for_status()
        url = response.json().get("url")
        if url:
            click.secho(
                _("Launching {} in your default browser...").format(url), fg="cyan"
            )
            webbrowser.open(url)
        else:
            click.secho(_("Failed to retrieve the Web UI URL."), fg="red", err=True)
    except Exception as e:
        click.secho(_("An unexpected error occurred: {}").format(e), fg="red", err=True)

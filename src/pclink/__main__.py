# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click
import requests

from .core import constants
from .core.config import config_manager
from .core.startup import StartupManager
from .core.version import __version__
from .core.web_auth import web_auth_manager

try:
    import qrcode
    from qrcode import constants as qr_constants
except ImportError:
    qrcode = None

try:
    import questionary
except ImportError:
    questionary = None

try:
    from prettytable import PrettyTable
except ImportError:
    PrettyTable = None

_ = gettext.gettext

CONTROL_API_URL = f"http://127.0.0.1:{constants.CONTROL_PORT}"


# ==========================================
# Helpers & Utilities
# ==========================================


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
    import requests
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
        if isinstance(items, dict):  # For blacklist
            keys = list(items.keys())
            if 0 <= idx < len(keys):
                return keys[idx]
        elif isinstance(items, list):
            if 0 <= idx < len(items):
                return items[idx][id_key]
    return id_or_idx


def _run_interactive_menu(title, choices, action_map):
    """Shared handler for processing interactive menus."""
    while True:
        action = questionary.select(title, choices=choices).ask()
        if action in ("back", "exit", None):
            break
        if action in action_map:
            action_map[action]()
        click.echo("")


# ==========================================
# Core Operations
# ==========================================


def _start_server_process():
    """Launches the main PCLink process in a fully detached state."""
    try:
        launcher_path = os.path.join(os.path.dirname(__file__), "launcher.py")
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


# ==========================================
# Base CLI Setup
# ==========================================


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """PCLink Server Control Interface."""
    import multiprocessing

    multiprocessing.freeze_support()

    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty():
            launch_interactive_menu(ctx)
        else:
            ctx.invoke(start)


# ==========================================
# Service Control Commands
# ==========================================


@cli.command(help=_("Start the PCLink background daemon."))
def start():
    if is_server_running():
        click.secho(_("PCLink daemon is already active."), fg="yellow")
        return

    click.secho(_("Initiating PCLink daemon..."), fg="cyan")
    if _start_server_process():
        click.secho(_("✓ PCLink daemon started successfully."), fg="green", bold=True)
    else:
        click.secho(
            _(
                "✗ Failed to initialize PCLink daemon. Please consult the logs for further details."
            ),
            fg="red",
            bold=True,
            err=True,
        )


@cli.command(help=_("Stop the active PCLink daemon."))
def stop():
    if not is_server_running():
        click.secho(_("PCLink daemon is not currently active."), fg="yellow")
        return

    try:
        click.secho(_("Transmitting shutdown signal to PCLink daemon..."), fg="cyan")
        requests.post(f"{CONTROL_API_URL}/stop", timeout=1)
    except Exception:
        pass

    click.secho(_("Awaiting daemon termination..."), fg="cyan")
    if _wait_for_condition(lambda: not is_server_running(), 5):
        click.secho(
            _("✓ PCLink daemon terminated successfully."), fg="green", bold=True
        )
    else:
        click.secho(
            _("✗ PCLink daemon termination timed out or failed."),
            fg="red",
            bold=True,
            err=True,
        )


@cli.command(help=_("Restart the active PCLink daemon."))
def restart():
    if not is_server_running():
        click.secho(
            _("PCLink daemon is not active. Execute 'start' command instead."),
            fg="yellow",
        )
        return

    try:
        click.secho(_("Initiating daemon restart sequence..."), fg="cyan")
        response = requests.post(f"{CONTROL_API_URL}/restart", timeout=5)
        response.raise_for_status()
        click.secho(
            _("✓ {}").format(
                response.json().get("message", _("PCLink is restarting."))
            ),
            fg="green",
            bold=True,
        )
    except Exception as e:
        click.secho(_("An unexpected error occurred: {}").format(e), fg="red", err=True)


@cli.command(help=_("Display the current operational status of the PCLink daemon."))
def status():
    try:
        response = requests.get(f"{CONTROL_API_URL}/status", timeout=1)
        response.raise_for_status()
        data = response.json()

        state = data.get("status", "unknown").title()
        port = data.get("port")
        mobile_api = _("Enabled") if data.get("mobile_api_enabled") else _("Disabled")
        state_color = "green" if state.lower() == "running" else "yellow"

        click.echo(
            click.style(_("PCLink Operational Status: "), bold=True)
            + click.style(state, fg=state_color, bold=True)
        )
        click.echo(
            click.style(_("  • Web UI Port: "), bold=True)
            + click.style(str(port), fg="cyan")
        )
        click.echo(
            click.style(_("  • Mobile API: "), bold=True)
            + click.style(mobile_api, fg="cyan")
        )
    except Exception:
        click.secho(_("PCLink daemon is not currently active."), fg="yellow")


@cli.command(name="ui", help=_("Launch the Web UI dashboard in the default browser."))
def ui():
    if is_server_running():
        _open_browser()
    else:
        click.secho(
            _("PCLink is not running. Initiating startup sequence..."), fg="cyan"
        )
        if _start_server_process():
            click.secho(
                _("✓ PCLink daemon started successfully."), fg="green", bold=True
            )
            _open_browser()
        else:
            click.secho(
                _("✗ Failed to start the PCLink daemon. Cannot launch Web UI."),
                fg="red",
                bold=True,
                err=True,
            )


@cli.command(help=_("Display or continuously follow the application log file."))
@click.option("--follow", "-f", is_flag=True, help=_("Follow log output continuously."))
def logs(follow):
    log_file = constants.APP_DATA_PATH / "pclink.log"
    if not log_file.exists():
        click.secho(_("Log file not found at: {}").format(log_file), fg="red", err=True)
        return

    try:
        with open(log_file, "r") as f:
            if not follow:
                click.echo(f.read())
            else:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    click.echo(line, nl=False)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        click.secho(_("Error reading log file: {}").format(e), fg="red", err=True)


# ==========================================
# Setup & Updates
# ==========================================


@cli.command(help=_("Initialize the primary administrator password for the Web UI."))
def setup():
    if web_auth_manager.is_setup_completed():
        click.secho(
            _(
                "Administrator setup is already complete. Use the Web UI to modify your credentials."
            ),
            fg="yellow",
        )
        return

    click.secho(_("=== PCLink Initial Configuration ==="), fg="cyan", bold=True)
    password = click.prompt(
        _("Create an administrator password for the Web UI (minimum 8 characters)"),
        hide_input=True,
    )
    confirm_password = click.prompt(_("Confirm password"), hide_input=True)

    if len(password) < 8:
        click.secho(
            _("Error: Password must be at least 8 characters in length."),
            fg="red",
            err=True,
        )
        return

    if password != confirm_password:
        click.secho(_("Error: Passwords do not match."), fg="red", err=True)
        return

    if web_auth_manager.setup_password(password):
        click.secho(
            _("\n✓ Administrator password established successfully!\n"),
            fg="green",
            bold=True,
        )
        click.echo(_("Next steps:"))
        click.echo(
            click.style("  1. ", bold=True) + _("Initialize daemon: pclink start")
        )
        click.echo(
            click.style("  2. ", bold=True)
            + _("Access Web UI: https://localhost:38080/ui/")
        )
        click.echo(
            click.style("  3. ", bold=True)
            + _("Retrieve pairing code: pclink device get-qr")
        )
    else:
        click.secho(
            _("✗ Error: Failed to establish administrator password."),
            fg="red",
            bold=True,
            err=True,
        )


@cli.command(name="update", help=_("Check for and install PCLink application updates."))
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help=_("Force update or reinstall even if up to date."),
)
@click.option(
    "--yes", "-y", is_flag=True, help=_("Automatically confirm installation prompts.")
)
def update_command(force: bool, yes: bool):
    from .core.update_checker import UpdateChecker

    click.secho(_("Checking for PCLink updates..."), fg="cyan")
    update_info = UpdateChecker().check_for_updates()
    current_v = __version__

    if not update_info and not force:
        click.secho(
            _("✓ PCLink v{} is already up to date.").format(current_v),
            fg="green",
            bold=True,
        )
        return

    latest_v = update_info.get("version") if update_info else current_v
    click.secho(
        _("New version available: v{} -> v{}").format(current_v, latest_v)
        if update_info
        else _("Forcing reinstall for PCLink v{}...").format(current_v),
        fg="yellow",
        bold=True,
    )

    if not yes and not click.confirm(_("Do you wish to proceed with the update?")):
        return click.echo(_("Update cancelled."))

    was_running = is_server_running()
    if was_running:
        click.secho(_("Stopping active PCLink daemon for upgrade..."), fg="cyan")
        try:
            requests.post(f"{CONTROL_API_URL}/stop", timeout=2)
            time.sleep(1)
        except Exception:
            pass

    success = False
    if sys.platform.startswith("linux"):
        click.secho(_("Executing smart Linux updater..."), fg="cyan")
        try:
            success = (
                subprocess.run(
                    [
                        "bash",
                        "-c",
                        "curl -fsSL https://raw.githubusercontent.com/BYTEDz/PCLink/main/install.sh | bash -s -- -u -y",
                    ]
                ).returncode
                == 0
            )
        except Exception as e:
            click.secho(_("Installer script failed: {}").format(e), fg="red", err=True)

    if not success:
        click.secho(_("Attempting upgrade via Python package manager..."), fg="cyan")
        pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "pclink"]
        try:
            if subprocess.run(pip_cmd).returncode == 0:
                success = True
            else:
                success = (
                    subprocess.run(pip_cmd + ["--break-system-packages"]).returncode
                    == 0
                )
        except Exception as e:
            click.secho(_("Pip upgrade failed: {}").format(e), fg="red", err=True)

    if success:
        click.secho(_("✓ PCLink upgrade complete!"), fg="green", bold=True)
        if was_running:
            click.secho(_("Restarting PCLink daemon..."), fg="cyan")
            _start_server_process()
    else:
        click.secho(
            _("✗ Failed to update PCLink automatically."), fg="red", bold=True, err=True
        )


# ==========================================
# Configuration Group
# ==========================================


@cli.group(help=_("Manage PCLink config (set autostart, set tray)."))
def config():
    pass


@config.group(name="set", help=_("Modify specific configuration keys."))
def config_set():
    pass


@config_set.command(
    name="autostart", help=_("Configure automatic startup on system boot.")
)
@click.argument("state", type=click.Choice(["enable", "disable"]))
def config_set_autostart(state):
    is_enable = state == "enable"
    try:
        manager = StartupManager()
        success = manager.enable() if is_enable else manager.disable()
        if success:
            config_manager.set("auto_start", is_enable)
            msg = (
                _("✓ Automatic startup enabled. PCLink will initialize on system boot.")
                if is_enable
                else _(
                    "✓ Automatic startup disabled. PCLink will no longer initialize on system boot."
                )
            )
            click.secho(msg, fg="green")
        else:
            msg = (
                _("✗ Failed to enable automatic startup.")
                if is_enable
                else _("✗ Failed to disable automatic startup.")
            )
            click.secho(msg, fg="red", err=True)
    except Exception as e:
        click.secho(_("Configuration error: {}").format(e), fg="red", err=True)


@config_set.command(name="tray", help=_("Configure the system tray icon visibility."))
@click.argument("state", type=click.Choice(["enable", "disable"]))
def config_set_tray(state):
    is_enabled = state == "enable"
    config_manager.set("enable_tray_icon", is_enabled)
    if is_enabled:
        click.secho(
            _(
                "✓ System tray icon enabled. Please restart the PCLink daemon to apply changes."
            ),
            fg="green",
        )
    else:
        click.secho(
            _(
                "✓ System tray icon disabled. PCLink will operate in headless mode on next start."
            ),
            fg="green",
        )


# ==========================================
# Device Management Group
# ==========================================


def _get_pending_pairings(port: int):
    """Helper to fetch pending pairings from the local server or fallback directly to SQLite."""
    if is_server_running():
        data = _get_api_data(f"https://127.0.0.1:{port}/ui/pairing/list")
        if data and "requests" in data:
            return data.get("requests", [])

    from .core.device_manager import device_manager

    return [
        {
            "pairing_id": d.device_id,
            "device_name": d.device_name,
            "ip": d.current_ip,
            "platform": d.platform,
        }
        for d in device_manager.get_all_devices()
        if not d.is_approved
    ]


def _process_pairing(id_or_idx, action, success_msg, error_msg):
    """Unified handler for approving or denying a pairing request."""
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)

    if not requests_list:
        return click.secho(_("No pending pairing requests found."), fg="yellow")

    target_id = id_or_idx
    if not target_id:
        if questionary:
            choices = [
                questionary.Choice(
                    title=f"{req.get('device_name', 'Unknown')} [{req.get('platform', 'N/A')}] (IP: {req.get('ip', 'N/A')})",
                    value=req["pairing_id"],
                )
                for req in requests_list
            ] + [questionary.Choice(title=_("Cancel"), value=None)]

            target_id = questionary.select(
                _(f"Select pending device request to {action.upper()}:"),
                choices=choices,
            ).ask()
            if not target_id:
                return
        else:
            list_requests()
            val = click.prompt(_(f"Select request index to {action.upper()}"), type=int)
            if 0 < val <= len(requests_list):
                target_id = requests_list[val - 1]["pairing_id"]
    elif str(target_id).isdigit():
        idx = int(target_id)
        if 0 < idx <= len(requests_list):
            target_id = requests_list[idx - 1]["pairing_id"]

    if not target_id:
        return click.secho(_("Error: Invalid selection."), fg="red", err=True)

    success = False
    if is_server_running():
        api_url = f"https://127.0.0.1:{port}/ui/pairing/{action}"
        success = _post_api_data(
            api_url, json={"pairing_id": target_id}
        ) or _post_api_data(api_url, params={"pairing_id": target_id})

    if not success:
        from .core.device_manager import device_manager

        success = (
            device_manager.approve_device(target_id)
            if action == "approve"
            else device_manager.revoke_device(target_id)
        )

    if success:
        click.secho(
            success_msg.format(target_id),
            fg="green" if action == "approve" else "yellow",
            bold=True,
        )
    else:
        click.secho(error_msg, fg="red", err=True)


PERM_ROLES = {
    "admin": [
        "files_read",
        "files_write",
        "processes",
        "power",
        "info",
        "input",
        "media",
        "terminal",
        "macros",
        "extensions",
        "apps",
        "screenshot",
        "desktop_streaming",
    ],
    "viewer": ["files_read", "info", "apps"],
    "media": ["media", "info", "apps"],
    "remote": ["input", "screenshot", "info", "media"],
    "none": [],
}


@cli.group(
    name="device",
    help=_("Manage devices (list, requests, approve, reject, get-qr, ban, etc)."),
)
def device_group():
    pass


@device_group.command(name="list", help=_("List all currently paired devices."))
@click.option(
    "--all", "-a", is_flag=True, help=_("Include unapproved/pending pairing requests.")
)
def list_devices(all: bool = False):
    port = config_manager.get("server_port", 38080)
    data = (
        _get_api_data(
            f"https://127.0.0.1:{port}/ui/devices",
            params={"include_unapproved": str(all).lower()},
        )
        if is_server_running()
        else None
    )

    devices = data.get("devices", []) if data else []
    if not devices:
        from .core.device_manager import device_manager

        for d in device_manager.get_all_devices():
            if d.is_approved or all:
                devices.append(
                    {
                        "id": d.device_id,
                        "name": d.device_name,
                        "ip": d.current_ip,
                        "platform": d.platform,
                        "last_seen": d.last_seen.isoformat(),
                        "is_approved": d.is_approved,
                        "is_online": False,
                    }
                )

    if not devices:
        pending = _get_pending_pairings(port)
        if pending:
            click.secho(
                _(
                    "No approved devices found, but {} pending pairing request(s) exist."
                ).format(len(pending)),
                fg="yellow",
                bold=True,
            )
            click.echo(
                _(
                    "Execute 'pclink device approve' or 'pclink device requests' to approve them."
                )
            )
        else:
            click.secho(_("No paired devices found."), fg="yellow")
        return

    rows = []
    for idx, d in enumerate(devices, 1):
        status_str = _("Approved") if d.get("is_approved") else _("Pending")
        if d.get("is_online"):
            status_str += f" ({_('Online')})"
        rows.append(
            [idx, d["name"], d["ip"], d["platform"], status_str, d["last_seen"]]
        )

    _print_table(
        [_("ID"), _("Device"), _("IP"), _("Platform"), _("Status"), _("Last Seen")],
        rows,
        [3, 20, 15, 10, 15, 25],
    )


@device_group.command(name="requests", help=_("List pending device pairing requests."))
def list_requests():
    requests_list = _get_pending_pairings(config_manager.get("server_port", 38080))
    if not requests_list:
        return click.secho(_("No pending pairing requests found."), fg="yellow")

    rows = [
        [idx, r["device_name"], r["ip"], r["platform"]]
        for idx, r in enumerate(requests_list, 1)
    ]
    _print_table([_("ID"), _("Device"), _("IP"), _("Platform")], rows, [3, 20, 15, 15])


@device_group.command(
    name="approve", help=_("Approve a pending device pairing request.")
)
@click.argument("id_or_idx", required=False)
def approve_pairing(id_or_idx: str = None):
    _process_pairing(
        id_or_idx,
        "approve",
        _("✓ Approved pairing request {}."),
        _("Error: Failed to approve pairing request."),
    )


@device_group.command(name="reject", help=_("Reject a pending device pairing request."))
@click.argument("id_or_idx", required=False)
def reject_pairing(id_or_idx: str = None):
    _process_pairing(
        id_or_idx,
        "deny",
        _("✗ Rejected pairing request {}."),
        _("Error: Failed to reject pairing request."),
    )


@device_group.command(name="revoke", help=_("Revoke access for a paired device."))
@click.argument("id_or_idx")
def revoke_device(id_or_idx: str):
    port = config_manager.get("server_port", 38080)
    target_id = _resolve_target_id(id_or_idx, "devices", "devices", "id")

    success = (
        _post_api_data(
            f"https://127.0.0.1:{port}/ui/devices/revoke",
            params={"device_id": target_id},
        )
        if is_server_running()
        else False
    )
    if not success:
        from .core.device_manager import device_manager

        success = device_manager.revoke_device(target_id)

    if success:
        click.secho(
            _("✓ Access revoked for device {}.").format(target_id),
            fg="green",
            bold=True,
        )
    else:
        click.secho(_("Error: Failed to revoke device access."), fg="red", err=True)


@device_group.command(name="ban", help=_("Ban a device permanently by hardware ID."))
@click.argument("id_or_idx")
def ban_device(id_or_idx: str):
    port = config_manager.get("server_port", 38080)
    target_id = _resolve_target_id(id_or_idx, "devices", "devices", "id")

    success = (
        _post_api_data(
            f"https://127.0.0.1:{port}/ui/devices/ban", params={"device_id": target_id}
        )
        if is_server_running()
        else False
    )
    if not success:
        from .core.device_manager import device_manager

        device = device_manager.get_device_by_id(target_id)
        if device and device.hardware_id:
            success = device_manager.ban_hardware(
                device.hardware_id, "Manual ban via CLI"
            )

    if success:
        click.secho(
            _("✓ Device {} banned permanently.").format(target_id), fg="red", bold=True
        )
    else:
        click.secho(_("Error: Failed to execute device ban."), fg="red", err=True)


@device_group.command(name="unban", help=_("Remove a hardware ID from the ban list."))
@click.argument("id_or_idx")
def unban_device(id_or_idx: str):
    port = config_manager.get("server_port", 38080)
    target_hwid = _resolve_target_id(id_or_idx, "devices/blacklist", "blacklist")

    success = (
        _post_api_data(
            f"https://127.0.0.1:{port}/ui/devices/unban",
            params={"hardware_id": target_hwid},
        )
        if is_server_running()
        else False
    )
    if not success:
        from .core.device_manager import device_manager

        success = device_manager.unban_hardware(target_hwid)

    if success:
        click.secho(
            _("✓ Hardware ID {} unbanned.").format(target_hwid), fg="green", bold=True
        )
    else:
        click.secho(_("Error: Failed to unban hardware ID."), fg="red", err=True)


@device_group.command(name="blacklist", help=_("List all banned hardware IDs."))
def list_blacklist():
    data = (
        _get_api_data(
            f"https://127.0.0.1:{config_manager.get('server_port', 38080)}/ui/devices/blacklist"
        )
        if is_server_running()
        else None
    )

    blacklist = data.get("blacklist", {}) if data else {}
    if not blacklist:
        from .core.device_manager import device_manager

        blacklist = {
            item["hardware_id"]: item.get("reason", "Manual ban")
            for item in device_manager.get_blacklist()
        }

    if not blacklist:
        return click.secho(_("The hardware ban list is currently empty."), fg="yellow")

    rows = [
        [idx, hwid, reason] for idx, (hwid, reason) in enumerate(blacklist.items(), 1)
    ]
    _print_table([_("ID"), _("Hardware ID"), _("Reason")], rows, [3, 40, 25])


@device_group.command(
    name="perm", help=_("Assign a permission role to a specific device.")
)
@click.argument("id_or_idx")
@click.argument("role", type=click.Choice(list(PERM_ROLES.keys())))
def update_perms(id_or_idx: str, role: str):
    port = config_manager.get("server_port", 38080)
    target_id = _resolve_target_id(id_or_idx, "devices", "devices", "id")
    perms = PERM_ROLES.get(role, [])

    success = (
        _post_api_data(
            f"https://127.0.0.1:{port}/ui/devices/{target_id}/permissions/bulk",
            json={"permissions": perms},
        )
        if is_server_running()
        else False
    )
    if not success:
        from .core.device_manager import device_manager

        device = device_manager.get_device_by_id(target_id)
        if device:
            device.permissions = perms
            device_manager._save_device(device)
            success = True

    if success:
        click.secho(
            _("✓ Role '{}' applied successfully to device {}.").format(role, target_id),
            fg="cyan",
            bold=True,
        )
    else:
        click.secho(
            _("Error: Failed to modify device permissions."), fg="red", err=True
        )


@device_group.command(
    name="get-qr", help=_("Display pairing information and QR code for mobile devices.")
)
def get_qr():
    if qrcode is None:
        return click.secho(
            _("Error: 'qrcode' library is not installed. Please install it via pip."),
            fg="red",
            err=True,
        )

    if not web_auth_manager.is_setup_completed():
        return click.secho(
            _(
                "Administrator setup is incomplete. Execute 'pclink setup' prior to retrieving pairing information."
            ),
            fg="yellow",
            err=True,
        )

    if not is_server_running():
        return click.secho(
            _(
                "PCLink daemon is offline. Execute 'pclink start' to retrieve pairing information."
            ),
            fg="yellow",
            err=True,
        )

    if not web_auth_manager.verify_password(
        click.prompt(_("Enter Administrator Password"), hide_input=True)
    ):
        return click.secho(
            _("Authentication failed. Incorrect password."), fg="red", err=True
        )

    try:
        response = requests.get(f"{CONTROL_API_URL}/qr-data", timeout=5)
        response.raise_for_status()
        qr_data = response.json().get("qr_data")

        if not qr_data:
            return click.secho(
                _("Failed to retrieve pairing data from the daemon."),
                fg="red",
                err=True,
            )

        click.secho(
            _("\n=== PCLink Device Pairing Information ===\n"), fg="cyan", bold=True
        )

        qr_obj = qrcode.QRCode(
            error_correction=qr_constants.ERROR_CORRECT_L, box_size=1, border=4
        )
        qr_obj.add_data(qr_data)
        qr_obj.make(fit=True)

        try:
            qr_obj.print_tty()
            click.echo("")
        except Exception:
            click.secho(
                _("(QR code display not available in this terminal environment)\n"),
                fg="yellow",
            )

        click.secho(_("Manual Pairing Code:"), bold=True)
        click.echo(f"{qr_data}\n")
        click.secho(
            _(
                "Scan the QR code or manually enter the code above in the PCLink mobile client."
            ),
            fg="cyan",
        )

    except Exception as e:
        click.secho(_("Failed to fetch pairing data: {}").format(e), fg="red", err=True)


# ==========================================
# Diagnostic & Repair Group
# ==========================================


@cli.group(help=_("Diagnostic and repair utilities (diagnose, fix, wayland)."))
def repair():
    pass


@repair.command(
    help=_("Execute diagnostic checks on system configuration and network state.")
)
def diagnose():
    from .services.repair_service import repair_service

    click.secho(_("Initiating system diagnostics..."), fg="cyan")
    results = asyncio.run(repair_service.run_diagnostics())

    for component, res in results.items():
        msg, status = res.get("message"), res.get("status")
        color = (
            "green" if status == "ok" else "yellow" if status == "warning" else "red"
        )
        symbol = "✓" if status == "ok" else "⚠" if status == "warning" else "✗"
        click.secho(_("{} {}: {}").format(symbol, component.upper(), msg), fg=color)


@repair.command(
    name="fix", help=_("Attempt to automatically resolve a specified issue.")
)
@click.argument("issue_id", type=click.Choice(["port", "firewall", "config", "db"]))
@click.option(
    "--kill",
    is_flag=True,
    help=_("Terminate the conflicting process (applicable to port issues)."),
)
@click.option(
    "--change-port",
    "change_port_flag",
    is_flag=True,
    help=_("Assign a new port automatically (applicable to port issues)."),
)
def run_repair(issue_id: str, kill: bool, change_port_flag: bool):
    from .services.repair_service import repair_service
    import getpass

    click.secho(_("Attempting to resolve issue: {}").format(issue_id), fg="cyan")
    res = {}
    if issue_id == "db":
        res = repair_service.fix_db()
    elif issue_id == "config":
        res = repair_service.fix_config()
    elif issue_id == "firewall":
        pwd = (
            getpass.getpass(_("Enter sudo password (leave blank if passwordless): "))
            if sys.platform.startswith("linux")
            else None
        )
        res = repair_service.fix_firewall(password=pwd)
    elif issue_id == "port":
        if kill:
            action = "kill_process"
        elif change_port_flag:
            action = "change_port"
        else:
            return click.secho(
                _(
                    "Error: Resolution strategy required for port issues. Specify '--kill' or '--change-port'."
                ),
                fg="red",
                err=True,
            )
        res = repair_service.fix_port(action)

    if res.get("status") == "ok":
        click.secho(_("✓ Success: {}").format(res.get("message")), fg="green")
    else:
        click.secho(_("✗ Failed: {}").format(res.get("message")), fg="red")


@repair.command(
    name="wayland", help=_("Resolve input emulation issues in Wayland environments.")
)
def repair_wayland():
    if sys.platform != "linux":
        return click.secho(
            _("This utility is exclusively for Linux systems operating under Wayland."),
            fg="red",
            err=True,
        )

    from .core.wayland_utils import (
        check_uinput_access,
        is_wayland,
        setup_uinput_permissions,
    )

    if not is_wayland() and not click.confirm(
        _("Wayland environment not detected. Proceed anyway?")
    ):
        return

    if check_uinput_access():
        click.secho(_("✓ Write access to /dev/uinput is already granted."), fg="green")
        return click.secho(
            _(
                "If input emulation is still malfunctioning, please restart the mobile client and attempt reconnection."
            ),
            fg="cyan",
        )

    click.secho(_("=== Wayland Input Emulation Patch ==="), fg="cyan", bold=True)
    click.echo(
        _(
            "PCLink requires elevated privileges to instantiate virtual input devices.\nExecute the following command with root privileges:\n"
        )
    )
    click.secho(setup_uinput_permissions(), fg="yellow", bold=True)
    click.secho(
        _(
            "\nNotice: A system restart or session logout is required for modifications to take effect."
        ),
        fg="magenta",
    )


# ==========================================
# Interactive Menus
# ==========================================


def _pending_requests_menu(ctx):
    if not _get_pending_pairings(config_manager.get("server_port", 38080)):
        return click.secho(_("No pending pairing requests found."), fg="yellow")

    ctx.invoke(list_requests)
    choices = [
        questionary.Choice(_("Approve a Request"), value="approve"),
        questionary.Choice(_("Reject a Request"), value="reject"),
        questionary.Choice(_("Back"), value="back"),
    ]
    action_map = {
        "approve": lambda: ctx.invoke(approve_pairing, id_or_idx=None),
        "reject": lambda: ctx.invoke(reject_pairing, id_or_idx=None),
    }
    _run_interactive_menu(_("Pending Request Action:"), choices, action_map)


def _device_menu(ctx):
    def _prompt_and_run(cmd, prompt_msg, list_cmd=None):
        if list_cmd:
            ctx.invoke(list_cmd, all=False) if list_cmd == list_devices else ctx.invoke(
                list_cmd
            )
        val = questionary.text(prompt_msg).ask()
        if val:
            ctx.invoke(cmd, id_or_idx=val)

    choices = [
        questionary.Choice(_("List Paired Devices"), value="list"),
        questionary.Choice(_("Pending Pairing Requests"), value="requests"),
        questionary.Choice(_("Get Pairing QR Code"), value="get_qr"),
        questionary.Choice(_("Revoke Device Access"), value="revoke"),
        questionary.Choice(_("Ban Device"), value="ban"),
        questionary.Choice(_("Unban Device"), value="unban"),
        questionary.Choice(_("List Banlist (Blacklist)"), value="blacklist"),
        questionary.Choice(_("Back to Main Menu"), value="back"),
    ]
    action_map = {
        "list": lambda: ctx.invoke(list_devices, all=False),
        "requests": lambda: _pending_requests_menu(ctx),
        "get_qr": lambda: ctx.invoke(get_qr),
        "revoke": lambda: _prompt_and_run(
            revoke_device,
            _("Enter Device ID or Index to Revoke (or press Enter to cancel):"),
            list_devices,
        ),
        "ban": lambda: _prompt_and_run(
            ban_device,
            _("Enter Device ID or Index to Ban (or press Enter to cancel):"),
            list_devices,
        ),
        "unban": lambda: _prompt_and_run(
            unban_device,
            _("Enter Hardware ID or Index to Unban (or press Enter to cancel):"),
            list_blacklist,
        ),
        "blacklist": lambda: ctx.invoke(list_blacklist),
    }
    _run_interactive_menu(_("Manage Devices & Pairing:"), choices, action_map)


def _config_menu(ctx):
    choices = [
        questionary.Choice(_("Enable Autostart"), value="auto_en"),
        questionary.Choice(_("Disable Autostart"), value="auto_dis"),
        questionary.Choice(_("Enable System Tray"), value="tray_en"),
        questionary.Choice(_("Disable System Tray"), value="tray_dis"),
        questionary.Choice(_("Back to Main Menu"), value="back"),
    ]
    action_map = {
        "auto_en": lambda: ctx.invoke(config_set_autostart, state="enable"),
        "auto_dis": lambda: ctx.invoke(config_set_autostart, state="disable"),
        "tray_en": lambda: ctx.invoke(config_set_tray, state="enable"),
        "tray_dis": lambda: ctx.invoke(config_set_tray, state="disable"),
    }
    _run_interactive_menu(_("Configuration:"), choices, action_map)


def _repair_menu(ctx):
    def _fix_port():
        strat = questionary.select(
            _("Select Port Resolution Strategy:"),
            choices=[
                questionary.Choice(_("Kill Conflicting Process"), value="kill"),
                questionary.Choice(_("Auto-Assign New Port"), value="change"),
                questionary.Choice(_("Cancel"), value="cancel"),
            ],
        ).ask()
        if strat == "kill":
            ctx.invoke(run_repair, issue_id="port", kill=True, change_port_flag=False)
        elif strat == "change":
            ctx.invoke(run_repair, issue_id="port", kill=False, change_port_flag=True)

    choices = [
        questionary.Choice(_("Run Diagnostics"), value="diagnose"),
        questionary.Choice(_("Fix Port Issue"), value="fix_port"),
        questionary.Choice(_("Fix Firewall Issue"), value="fix_firewall"),
        questionary.Choice(_("Fix Config Issue"), value="fix_config"),
        questionary.Choice(_("Fix Database Issue"), value="fix_db"),
        questionary.Choice(_("Apply Wayland Patch (Linux)"), value="wayland"),
        questionary.Choice(_("Back to Main Menu"), value="back"),
    ]
    action_map = {
        "diagnose": lambda: ctx.invoke(diagnose),
        "fix_port": _fix_port,
        "fix_firewall": lambda: ctx.invoke(
            run_repair, issue_id="firewall", kill=False, change_port_flag=False
        ),
        "fix_config": lambda: ctx.invoke(
            run_repair, issue_id="config", kill=False, change_port_flag=False
        ),
        "fix_db": lambda: ctx.invoke(
            run_repair, issue_id="db", kill=False, change_port_flag=False
        ),
        "wayland": lambda: ctx.invoke(repair_wayland),
    }
    _run_interactive_menu(_("Repair Center:"), choices, action_map)


def launch_interactive_menu(ctx):
    if not questionary:
        click.secho(
            _("Interactive mode requires 'questionary' (pip install questionary)."),
            fg="red",
            err=True,
        )
        return ctx.invoke(start)

    click.secho(_("\n=== PCLink Control Center ===\n"), fg="cyan", bold=True)
    choices = [
        questionary.Choice(_("Start PCLink Daemon"), value="start"),
        questionary.Choice(_("Stop PCLink Daemon"), value="stop"),
        questionary.Choice(_("Restart PCLink Daemon"), value="restart"),
        questionary.Choice(_("Status"), value="status"),
        questionary.Choice(_("Open Web UI"), value="ui"),
        questionary.Choice(_("Manage Devices & Pairing"), value="devices"),
        questionary.Choice(_("Configuration"), value="config"),
        questionary.Choice(_("Repair Center"), value="repair"),
        questionary.Choice(_("Check for Updates"), value="update"),
        questionary.Choice(_("View Logs"), value="logs"),
        questionary.Choice(_("Initial Admin Setup"), value="setup"),
        questionary.Choice(_("Exit"), value="exit"),
    ]
    action_map = {
        "start": lambda: ctx.invoke(start),
        "stop": lambda: ctx.invoke(stop),
        "restart": lambda: ctx.invoke(restart),
        "status": lambda: ctx.invoke(status),
        "ui": lambda: ctx.invoke(ui),
        "logs": lambda: ctx.invoke(logs, follow=False),
        "setup": lambda: ctx.invoke(setup),
        "devices": lambda: _device_menu(ctx),
        "config": lambda: _config_menu(ctx),
        "repair": lambda: _repair_menu(ctx),
        "update": lambda: ctx.invoke(update_command, force=False, yes=False),
    }
    _run_interactive_menu(_("Main Menu:"), choices, action_map)


if __name__ == "__main__":
    cli()

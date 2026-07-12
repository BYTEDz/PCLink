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


def is_server_running():
    """Checks if the internal control API is reachable."""
    try:
        response = requests.get(f"{CONTROL_API_URL}/status", timeout=0.5)
        return response.status_code == 200
    except requests.ConnectionError:
        return False
    except Exception:
        return False


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
        for _i in range(5):
            time.sleep(1)
            if is_server_running():
                return True
        return False
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
    except requests.RequestException as e:
        click.secho(
            _("Failed to communicate with PCLink daemon: {}").format(e),
            fg="red",
            err=True,
        )
    except Exception as e:
        click.secho(_("An unexpected error occurred: {}").format(e), fg="red", err=True)


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """PCLink Server Control Interface."""
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty():
            launch_interactive_menu(ctx)
        else:
            ctx.invoke(start)


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
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        pass
    except Exception as e:
        click.secho(
            _("An error occurred during daemon termination: {}").format(e),
            fg="red",
            err=True,
        )
        return

    click.secho(_("Awaiting daemon termination..."), fg="cyan")
    shutdown_success = False
    for _i in range(5):
        if not is_server_running():
            shutdown_success = True
            break
        time.sleep(1)

    if shutdown_success:
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
    except requests.RequestException as e:
        click.secho(
            _("Failed to connect to PCLink daemon for restart: {}").format(e),
            fg="red",
            err=True,
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
    except requests.RequestException:
        click.secho(_("PCLink daemon is not currently active."), fg="yellow")
    except Exception as e:
        click.secho(_("An unexpected error occurred: {}").format(e), fg="red", err=True)


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
    click.echo("")
    click.echo(
        _("Create an administrator password for the Web UI (minimum 8 characters)")
    )

    password = click.prompt(_("Password"), hide_input=True)
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
        click.echo("")
        click.secho(
            _("✓ Administrator password established successfully!"),
            fg="green",
            bold=True,
        )
        click.echo("")
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
    try:
        startup_manager = StartupManager()
        if state == "enable":
            if startup_manager.enable():
                config_manager.set("auto_start", True)
                click.secho(
                    _(
                        "✓ Automatic startup enabled. PCLink will initialize on system boot."
                    ),
                    fg="green",
                )
            else:
                click.secho(
                    _("✗ Failed to enable automatic startup."), fg="red", err=True
                )
        else:
            if startup_manager.disable():
                config_manager.set("auto_start", False)
                click.secho(
                    _(
                        "✓ Automatic startup disabled. PCLink will no longer initialize on system boot."
                    ),
                    fg="green",
                )
            else:
                click.secho(
                    _("✗ Failed to disable automatic startup."), fg="red", err=True
                )
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


def _get_pending_pairings(port: int):
    """Helper to fetch pairings from the local server."""
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        url = f"https://localhost:{port}/ui/pairing/list"
        res = requests.get(
            url, verify=False, headers={"X-Internal-Auth": "true"}, timeout=5
        )
        return res.json().get("requests", []) if res.status_code == 200 else []
    except Exception:
        return []


def _get_api_data(url: str, params=None):
    """Helper for CLI API calls."""
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        res = requests.get(
            url,
            params=params,
            verify=False,
            headers={"X-Internal-Auth": "true"},
            timeout=5,
        )
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def _post_api_data(url: str, params=None, json=None):
    """Helper for CLI API calls."""
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        res = requests.post(
            url,
            params=params,
            json=json,
            verify=False,
            headers={"X-Internal-Auth": "true"},
            timeout=5,
        )
        return res.status_code == 200
    except Exception:
        return False


PERM_ROLES = {
    "admin": [
        "files_browse",
        "files_download",
        "files_upload",
        "files_delete",
        "processes",
        "power",
        "info",
        "mouse",
        "keyboard",
        "media",
        "volume",
        "terminal",
        "macros",
        "extensions",
        "apps",
        "clipboard",
        "screenshot",
        "command",
        "wol",
        "desktop_streaming",
    ],
    "viewer": ["files_browse", "info", "apps"],
    "media": ["media", "volume", "info", "apps"],
    "remote": ["mouse", "keyboard", "screenshot", "info", "volume"],
    "none": [],
}


@cli.group(
    name="device",
    help=_("Manage devices (list, requests, approve, reject, get-qr, ban, etc)."),
)
def device_group():
    pass


@device_group.command(name="list", help=_("List all currently paired devices."))
def list_devices():
    port = config_manager.get("server_port", 38080)
    data = _get_api_data(f"https://localhost:{port}/ui/devices")
    if not data or not data.get("devices"):
        click.secho(_("No paired devices found."), fg="yellow")
        return

    if PrettyTable:
        table = PrettyTable()
        table.field_names = [
            _("ID"),
            _("Device"),
            _("IP"),
            _("Platform"),
            _("Last Seen"),
        ]
        table.align = "l"
        for idx, d in enumerate(data["devices"], 1):
            table.add_row([idx, d["name"], d["ip"], d["platform"], d["last_seen"]])
        click.echo(table)
    else:
        click.secho(
            f"{'#':<3} | {_('Device'):<20} | {_('IP'):<15} | {_('Platform'):<10} | {_('Last Seen')}",
            bold=True,
        )
        click.echo("-" * 75)
        for idx, d in enumerate(data["devices"], 1):
            click.echo(
                f"{idx:<3} | {d['name']:<20} | {d['ip']:<15} | {d['platform']:<10} | {d['last_seen']}"
            )


@device_group.command(name="requests", help=_("List pending device pairing requests."))
def list_requests():
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)

    if not requests_list:
        click.secho(_("No pending pairing requests found."), fg="yellow")
        return

    if PrettyTable:
        table = PrettyTable()
        table.field_names = [_("ID"), _("Device"), _("IP"), _("Platform")]
        table.align = "l"
        for idx, req in enumerate(requests_list, 1):
            table.add_row([idx, req["device_name"], req["ip"], req["platform"]])
        click.echo(table)
    else:
        click.secho(
            f"{'#':<3} | {_('Device'):<20} | {_('IP'):<15} | {_('Platform')}", bold=True
        )
        click.echo("-" * 60)
        for idx, req in enumerate(requests_list, 1):
            click.echo(
                f"{idx:<3} | {req['device_name']:<20} | {req['ip']:<15} | {req['platform']}"
            )


@device_group.command(
    name="approve", help=_("Approve a pending device pairing request.")
)
@click.argument("id_or_idx", required=False)
def approve_pairing(id_or_idx: str = None):
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)
    target_id = None

    if not requests_list:
        click.secho(_("No pending pairing requests found."), fg="yellow")
        return

    if not id_or_idx:
        list_requests()
        val = click.prompt(_("Select request index to APPROVE"), type=int)
        if 0 < val <= len(requests_list):
            target_id = requests_list[val - 1]["pairing_id"]
    elif id_or_idx.isdigit():
        idx = int(id_or_idx)
        if 0 < idx <= len(requests_list):
            target_id = requests_list[idx - 1]["pairing_id"]
    else:
        target_id = id_or_idx

    if not target_id:
        click.secho(_("Error: Invalid selection."), fg="red", err=True)
        return

    try:
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        url = f"https://localhost:{port}/ui/pairing/approve"
        response = requests.post(
            url,
            params={"pairing_id": target_id},
            verify=False,
            headers={"X-Internal-Auth": "true"},
            timeout=5,
        )
        if response.status_code == 200:
            click.secho(
                _("✓ Approved device {}.").format(target_id), fg="green", bold=True
            )
        else:
            click.secho(
                _("Operation failed: {}").format(response.text), fg="red", err=True
            )
    except Exception as e:
        click.secho(_("Error occurred: {}").format(e), fg="red", err=True)


@device_group.command(name="reject", help=_("Reject a pending device pairing request."))
@click.argument("id_or_idx", required=False)
def reject_pairing(id_or_idx: str = None):
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)
    target_id = None

    if not requests_list:
        click.secho(_("No pending pairing requests found."), fg="yellow")
        return

    if not id_or_idx:
        list_requests()
        val = click.prompt(_("Select request index to REJECT"), type=int)
        if 0 < val <= len(requests_list):
            target_id = requests_list[val - 1]["pairing_id"]
    elif id_or_idx.isdigit():
        idx = int(id_or_idx)
        if 0 < idx <= len(requests_list):
            target_id = requests_list[idx - 1]["pairing_id"]
    else:
        target_id = id_or_idx

    if not target_id:
        click.secho(_("Error: Invalid selection."), fg="red", err=True)
        return

    try:
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        url = f"https://localhost:{port}/ui/pairing/deny"
        response = requests.post(
            url,
            params={"pairing_id": target_id},
            verify=False,
            headers={"X-Internal-Auth": "true"},
            timeout=5,
        )
        if response.status_code == 200:
            click.secho(
                _("✗ Rejected device request {}.").format(target_id),
                fg="yellow",
                bold=True,
            )
        else:
            click.secho(
                _("Operation failed: {}").format(response.text), fg="red", err=True
            )
    except Exception as e:
        click.secho(_("Error occurred: {}").format(e), fg="red", err=True)


@device_group.command(name="revoke", help=_("Revoke access for a paired device."))
@click.argument("id_or_idx")
def revoke_device(id_or_idx: str):
    port = config_manager.get("server_port", 38080)
    target_id = id_or_idx
    if id_or_idx.isdigit():
        data = _get_api_data(f"https://localhost:{port}/ui/devices")
        if data and 0 < int(id_or_idx) <= len(data["devices"]):
            target_id = data["devices"][int(id_or_idx) - 1]["id"]

    if _post_api_data(
        f"https://localhost:{port}/ui/devices/revoke", params={"device_id": target_id}
    ):
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
    target_id = id_or_idx
    if id_or_idx.isdigit():
        data = _get_api_data(f"https://localhost:{port}/ui/devices")
        if data and 0 < int(id_or_idx) <= len(data["devices"]):
            target_id = data["devices"][int(id_or_idx) - 1]["id"]

    if _post_api_data(
        f"https://localhost:{port}/ui/devices/ban", params={"device_id": target_id}
    ):
        click.secho(
            _("✓ Device {} banned permanently.").format(target_id), fg="red", bold=True
        )
    else:
        click.secho(_("Error: Failed to execute device ban."), fg="red", err=True)


@device_group.command(name="unban", help=_("Remove a hardware ID from the ban list."))
@click.argument("hwid_or_idx")
def unban_device(hwid_or_idx: str):
    port = config_manager.get("server_port", 38080)
    target_hwid = hwid_or_idx
    if hwid_or_idx.isdigit():
        data = _get_api_data(f"https://localhost:{port}/ui/devices/blacklist")
        if data and 0 < int(hwid_or_idx) <= len(data["blacklist"]):
            target_hwid = list(data["blacklist"].keys())[int(hwid_or_idx) - 1]

    if _post_api_data(
        f"https://localhost:{port}/ui/devices/unban",
        params={"hardware_id": target_hwid},
    ):
        click.secho(
            _("✓ Hardware ID {} unbanned.").format(target_hwid), fg="green", bold=True
        )
    else:
        click.secho(_("Error: Failed to unban hardware ID."), fg="red", err=True)


@device_group.command(name="blacklist", help=_("List all banned hardware IDs."))
def list_blacklist():
    port = config_manager.get("server_port", 38080)
    data = _get_api_data(f"https://localhost:{port}/ui/devices/blacklist")
    if not data or not data.get("blacklist"):
        click.secho(_("The hardware ban list is currently empty."), fg="yellow")
        return

    if PrettyTable:
        table = PrettyTable()
        table.field_names = [_("ID"), _("Hardware ID"), _("Reason")]
        table.align = "l"
        for idx, (hwid, reason) in enumerate(data["blacklist"].items(), 1):
            table.add_row([idx, hwid, reason])
        click.echo(table)
    else:
        click.secho(f"{'#':<3} | {_('Hardware ID'):<40} | {_('Reason')}", bold=True)
        click.echo("-" * 65)
        for idx, (hwid, reason) in enumerate(data["blacklist"].items(), 1):
            click.echo(f"{idx:<3} | {hwid:<40} | {reason}")


@device_group.command(
    name="perm", help=_("Assign a permission role to a specific device.")
)
@click.argument("id_or_idx")
@click.argument("role", type=click.Choice(list(PERM_ROLES.keys())))
def update_perms(id_or_idx: str, role: str):
    port = config_manager.get("server_port", 38080)
    target_id = id_or_idx
    if id_or_idx.isdigit():
        data = _get_api_data(f"https://localhost:{port}/ui/devices")
        if data and 0 < int(id_or_idx) <= len(data["devices"]):
            target_id = data["devices"][int(id_or_idx) - 1]["id"]

    perms = PERM_ROLES.get(role, [])
    if _post_api_data(
        f"https://localhost:{port}/ui/devices/{target_id}/permissions/bulk",
        json={"permissions": perms},
    ):
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
        click.secho(
            _("Error: 'qrcode' library is not installed. Please install it via pip."),
            fg="red",
            err=True,
        )
        return

    if not web_auth_manager.is_setup_completed():
        click.secho(
            _(
                "Administrator setup is incomplete. Execute 'pclink setup' prior to retrieving pairing information."
            ),
            fg="yellow",
            err=True,
        )
        return

    if not is_server_running():
        click.secho(
            _(
                "PCLink daemon is offline. Execute 'pclink start' to retrieve pairing information."
            ),
            fg="yellow",
            err=True,
        )
        return

    password = click.prompt(_("Enter Administrator Password"), hide_input=True)

    if not web_auth_manager.verify_password(password):
        click.secho(_("Authentication failed. Incorrect password."), fg="red", err=True)
        return

    try:
        response = requests.get(f"{CONTROL_API_URL}/qr-data", timeout=5)
        response.raise_for_status()
        qr_data = response.json().get("qr_data")

        if not qr_data:
            click.secho(
                _("Failed to retrieve pairing data from the daemon."),
                fg="red",
                err=True,
            )
            return

        click.echo("")
        click.secho(
            _("=== PCLink Device Pairing Information ==="), fg="cyan", bold=True
        )
        click.echo("")

        qr_obj = qrcode.QRCode(
            error_correction=qr_constants.ERROR_CORRECT_L,
            box_size=1,
            border=4,
        )
        qr_obj.add_data(qr_data)
        qr_obj.make(fit=True)

        try:
            qr_obj.print_tty()
            click.echo("")
        except Exception:
            click.secho(
                _("(QR code display not available in this terminal environment)"),
                fg="yellow",
            )
            click.echo("")

        click.secho(_("Manual Pairing Code:"), bold=True)
        click.echo(qr_data)
        click.echo("")
        click.secho(
            _(
                "Scan the QR code or manually enter the code above in the PCLink mobile client."
            ),
            fg="cyan",
        )

    except requests.RequestException as e:
        click.secho(_("Failed to fetch pairing data: {}").format(e), fg="red", err=True)
    except Exception as e:
        click.secho(_("An unexpected error occurred: {}").format(e), fg="red", err=True)


@cli.group(help=_("Diagnostic and repair utilities (diagnose, fix, wayland)."))
def repair():
    pass


@repair.command(
    help=_("Execute diagnostic checks on system configuration and network state.")
)
def diagnose():
    from .services.repair_service import repair_service

    click.secho(_("Initiating system diagnostics..."), fg="cyan")
    results = repair_service.run_diagnostics()
    for component, res in results.items():
        status = res.get("status")
        msg = res.get("message")
        if status == "ok":
            click.secho(_("✓ {}: {}").format(component.upper(), msg), fg="green")
        elif status == "warning":
            click.secho(_("⚠ {}: {}").format(component.upper(), msg), fg="yellow")
        else:
            click.secho(_("✗ {}: {}").format(component.upper(), msg), fg="red")


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
    import sys
    import getpass

    click.secho(_("Attempting to resolve issue: {}").format(issue_id), fg="cyan")
    res = {}
    if issue_id == "db":
        res = repair_service.fix_db()
    elif issue_id == "config":
        res = repair_service.fix_config()
    elif issue_id == "firewall":
        pwd = None
        if sys.platform.startswith("linux"):
            click.secho(
                _("Firewall configuration on Linux may require elevated privileges."),
                fg="yellow",
            )
            pwd = getpass.getpass(
                _("Enter sudo password (leave blank if passwordless): ")
            )
        res = repair_service.fix_firewall(password=pwd)
    elif issue_id == "port":
        action = None
        if kill:
            action = "kill_process"
        elif change_port_flag:
            action = "change_port"
        else:
            click.secho(
                _(
                    "Error: Resolution strategy required for port issues. Specify '--kill' or '--change-port'."
                ),
                fg="red",
                err=True,
            )
            return
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
        click.secho(
            _("This utility is exclusively for Linux systems operating under Wayland."),
            fg="red",
            err=True,
        )
        return

    from .core.wayland_utils import (
        check_uinput_access,
        is_wayland,
        setup_uinput_permissions,
    )

    if not is_wayland():
        click.secho(
            _(
                "Wayland environment not detected. This patch is designed specifically for Wayland sessions."
            ),
            fg="yellow",
        )
        if not click.confirm(_("Do you wish to proceed anyway?")):
            return

    if check_uinput_access():
        click.secho(_("✓ Write access to /dev/uinput is already granted."), fg="green")
        click.secho(
            _(
                "If input emulation is still malfunctioning, please restart the mobile client and attempt reconnection."
            ),
            fg="cyan",
        )
        return

    click.secho(_("=== Wayland Input Emulation Patch ==="), fg="cyan", bold=True)
    click.echo(
        _("PCLink requires elevated privileges to instantiate virtual input devices.")
    )
    click.echo(
        _("Execute the following command with root privileges to grant access:\n")
    )
    click.secho(setup_uinput_permissions(), fg="yellow", bold=True)
    click.echo("")
    click.secho(
        _(
            "Notice: A system restart or session logout is required for group policy modifications to take effect."
        ),
        fg="magenta",
    )


def _device_menu(ctx):
    while True:
        action = questionary.select(
            _("Manage Devices & Pairing:"),
            choices=[
                questionary.Choice(_("List Paired Devices"), value="list"),
                questionary.Choice(_("List Pending Requests"), value="requests"),
                questionary.Choice(_("Approve Request"), value="approve"),
                questionary.Choice(_("Reject Request"), value="reject"),
                questionary.Choice(_("Get Pairing QR Code"), value="get_qr"),
                questionary.Choice(_("Revoke Device Access"), value="revoke"),
                questionary.Choice(_("Ban Device"), value="ban"),
                questionary.Choice(_("Unban Device"), value="unban"),
                questionary.Choice(_("List Banlist (Blacklist)"), value="blacklist"),
                questionary.Choice(_("Back to Main Menu"), value="back"),
            ],
        ).ask()

        if action == "list":
            ctx.invoke(list_devices)
        elif action == "requests":
            ctx.invoke(list_requests)
        elif action == "approve":
            ctx.invoke(approve_pairing, id_or_idx=None)
        elif action == "reject":
            ctx.invoke(reject_pairing, id_or_idx=None)
        elif action == "get_qr":
            ctx.invoke(get_qr)
        elif action == "revoke":
            ctx.invoke(list_devices)
            dev_id = questionary.text(
                _("Enter Device ID or Index to Revoke (or press Enter to cancel):")
            ).ask()
            if dev_id:
                ctx.invoke(revoke_device, id_or_idx=dev_id)
        elif action == "ban":
            ctx.invoke(list_devices)
            dev_id = questionary.text(
                _("Enter Device ID or Index to Ban (or press Enter to cancel):")
            ).ask()
            if dev_id:
                ctx.invoke(ban_device, id_or_idx=dev_id)
        elif action == "unban":
            ctx.invoke(list_blacklist)
            hwid = questionary.text(
                _("Enter Hardware ID or Index to Unban (or press Enter to cancel):")
            ).ask()
            if hwid:
                ctx.invoke(unban_device, hwid_or_idx=hwid)
        elif action == "blacklist":
            ctx.invoke(list_blacklist)
        elif action == "back" or action is None:
            break

        if action not in ["back", None]:
            click.echo("")


def _config_menu(ctx):
    while True:
        action = questionary.select(
            _("Configuration:"),
            choices=[
                questionary.Choice(_("Enable Autostart"), value="auto_en"),
                questionary.Choice(_("Disable Autostart"), value="auto_dis"),
                questionary.Choice(_("Enable System Tray"), value="tray_en"),
                questionary.Choice(_("Disable System Tray"), value="tray_dis"),
                questionary.Choice(_("Back to Main Menu"), value="back"),
            ],
        ).ask()

        if action == "auto_en":
            ctx.invoke(config_set_autostart, state="enable")
        elif action == "auto_dis":
            ctx.invoke(config_set_autostart, state="disable")
        elif action == "tray_en":
            ctx.invoke(config_set_tray, state="enable")
        elif action == "tray_dis":
            ctx.invoke(config_set_tray, state="disable")
        elif action == "back" or action is None:
            break

        if action not in ["back", None]:
            click.echo("")


def _repair_menu(ctx):
    while True:
        action = questionary.select(
            _("Repair Center:"),
            choices=[
                questionary.Choice(_("Run Diagnostics"), value="diagnose"),
                questionary.Choice(_("Fix Port Issue"), value="fix_port"),
                questionary.Choice(_("Fix Firewall Issue"), value="fix_firewall"),
                questionary.Choice(_("Fix Config Issue"), value="fix_config"),
                questionary.Choice(_("Fix Database Issue"), value="fix_db"),
                questionary.Choice(_("Apply Wayland Patch (Linux)"), value="wayland"),
                questionary.Choice(_("Back to Main Menu"), value="back"),
            ],
        ).ask()

        if action == "diagnose":
            ctx.invoke(diagnose)
        elif action == "fix_port":
            strat = questionary.select(
                _("Select Port Resolution Strategy:"),
                choices=[
                    questionary.Choice(_("Kill Conflicting Process"), value="kill"),
                    questionary.Choice(_("Auto-Assign New Port"), value="change"),
                    questionary.Choice(_("Cancel"), value="cancel"),
                ],
            ).ask()
            if strat == "kill":
                ctx.invoke(
                    run_repair, issue_id="port", kill=True, change_port_flag=False
                )
            elif strat == "change":
                ctx.invoke(
                    run_repair, issue_id="port", kill=False, change_port_flag=True
                )
        elif action == "fix_firewall":
            ctx.invoke(
                run_repair, issue_id="firewall", kill=False, change_port_flag=False
            )
        elif action == "fix_config":
            ctx.invoke(
                run_repair, issue_id="config", kill=False, change_port_flag=False
            )
        elif action == "fix_db":
            ctx.invoke(run_repair, issue_id="db", kill=False, change_port_flag=False)
        elif action == "wayland":
            ctx.invoke(repair_wayland)
        elif action == "back" or action is None:
            break

        if action not in ["back", None]:
            click.echo("")


def launch_interactive_menu(ctx):
    if not questionary:
        click.secho(
            _(
                "Interactive mode requires 'questionary'. To enable it, install via: pip install questionary"
            ),
            fg="red",
            err=True,
        )
        ctx.invoke(start)
        return

    click.secho(_("\n=== PCLink Control Center ===\n"), fg="cyan", bold=True)

    while True:
        action = questionary.select(
            _("Main Menu:"),
            choices=[
                questionary.Choice(_("Start PCLink Daemon"), value="start"),
                questionary.Choice(_("Stop PCLink Daemon"), value="stop"),
                questionary.Choice(_("Restart PCLink Daemon"), value="restart"),
                questionary.Choice(_("Status"), value="status"),
                questionary.Choice(_("Open Web UI"), value="ui"),
                questionary.Choice(_("Manage Devices & Pairing"), value="devices"),
                questionary.Choice(_("Configuration"), value="config"),
                questionary.Choice(_("Repair Center"), value="repair"),
                questionary.Choice(_("View Logs"), value="logs"),
                questionary.Choice(_("Initial Admin Setup"), value="setup"),
                questionary.Choice(_("Exit"), value="exit"),
            ],
        ).ask()

        if action == "start":
            ctx.invoke(start)
        elif action == "stop":
            ctx.invoke(stop)
        elif action == "restart":
            ctx.invoke(restart)
        elif action == "status":
            ctx.invoke(status)
        elif action == "ui":
            ctx.invoke(ui)
        elif action == "logs":
            ctx.invoke(logs, follow=False)
        elif action == "setup":
            ctx.invoke(setup)
        elif action == "devices":
            _device_menu(ctx)
        elif action == "config":
            _config_menu(ctx)
        elif action == "repair":
            _repair_menu(ctx)
        elif action == "exit" or action is None:
            break

        if action not in ["exit", None]:
            click.echo("")


if __name__ == "__main__":
    cli()

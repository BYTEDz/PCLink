# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

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
            # Prefer pythonw.exe to avoid console window if running from source
            if not getattr(sys, "frozen", False):
                pythonw = Path(executable).parent / "pythonw.exe"
                if pythonw.exists():
                    executable = str(pythonw)

            # Use CREATE_NO_WINDOW (0x08000000) to prevent console flash
            # Also use DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP for a clean background state
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | 0x08000000
            )
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen([executable, launcher_path], **kwargs)

        click.echo("Waiting for PCLink to initialize...")
        for _ in range(5):
            time.sleep(1)
            if is_server_running():
                return True
        return False
    except Exception as e:
        click.echo(f"Failed to start PCLink: {e}", err=True)
        return False


def _open_browser():
    """Opens the PCLink Web UI in the default browser."""
    if not is_server_running():
        click.echo("Cannot open Web UI because PCLink is not running.", err=True)
        return

    try:
        response = requests.get(f"{CONTROL_API_URL}/web-url", timeout=1)
        response.raise_for_status()
        url = response.json().get("url")
        if url:
            click.echo(f"Opening {url} in your browser...")
            webbrowser.open(url)
        else:
            click.echo("Could not retrieve Web UI URL.", err=True)
    except requests.RequestException as e:
        click.echo(f"Failed to contact PCLink service: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """PCLink Server Control Interface."""
    if ctx.invoked_subcommand is None:
        start()


@cli.command()
def start():
    """Start the PCLink service in the background."""
    if is_server_running():
        click.echo("PCLink is already running.")
        return

    click.echo("Starting PCLink in the background...")
    if _start_server_process():
        click.echo("PCLink started successfully.")
    else:
        click.echo("PCLink failed to start. Check logs for details.", err=True)


@cli.command()
def stop():
    """Stop the running PCLink service."""
    if not is_server_running():
        click.echo("PCLink is not running.")
        return

    try:
        click.echo("Sending shutdown signal to PCLink...")
        requests.post(f"{CONTROL_API_URL}/stop", timeout=1)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        pass
    except Exception as e:
        click.echo(f"An error occurred while sending the stop signal: {e}", err=True)
        return

    click.echo("Waiting for PCLink to shut down...")
    shutdown_success = False
    for _ in range(5):
        if not is_server_running():
            shutdown_success = True
            break
        time.sleep(1)

    if shutdown_success:
        click.echo("PCLink stopped successfully.")
    else:
        click.echo("PCLink did not stop as expected.", err=True)


@cli.command()
def restart():
    """Restart the running PCLink service."""
    if not is_server_running():
        click.echo("PCLink is not running. Use 'start' instead.")
        return

    try:
        click.echo("Restarting PCLink...")
        response = requests.post(f"{CONTROL_API_URL}/restart", timeout=5)
        response.raise_for_status()
        click.echo(response.json().get("message", "PCLink is restarting."))
    except requests.RequestException as e:
        click.echo(f"Could not connect to PCLink for restart: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@cli.command()
def status():
    """Check the status of the PCLink service."""
    try:
        response = requests.get(f"{CONTROL_API_URL}/status", timeout=1)
        response.raise_for_status()
        data = response.json()
        state = data.get("status", "unknown").title()
        port = data.get("port")
        mobile_api = "Enabled" if data.get("mobile_api_enabled") else "Disabled"

        click.echo(f"PCLink Status: {state}")
        click.echo(f"  - Web UI Port: {port}")
        click.echo(f"  - Mobile API: {mobile_api}")
    except requests.RequestException:
        click.echo("PCLink is not running.")
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@cli.command(name="open")
def open_webui():
    """Open WebUI if PCLink is already running."""
    _open_browser()


@cli.command()
def webui():
    """Start PCLink (if needed) and open the WebUI."""
    if is_server_running():
        click.echo("PCLink is already running.")
        _open_browser()
    else:
        click.echo("PCLink is not running. Starting it now...")
        if _start_server_process():
            click.echo("PCLink started successfully.")
            _open_browser()
        else:
            click.echo("PCLink failed to start. Cannot open Web UI.", err=True)


@cli.command()
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
def logs(follow):
    """Display the application log file."""
    log_file = constants.APP_DATA_PATH / "pclink.log"
    if not log_file.exists():
        click.echo(f"Log file not found at: {log_file}", err=True)
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
        click.echo(f"Error reading log file: {e}", err=True)


@cli.command()
def qr():
    """Display the connection QR code in the terminal."""
    if qrcode is None:
        click.echo("Error: 'qrcode' library is not installed.", err=True)
        click.echo("Please run: pip install qrcode", err=True)
        return

    if not is_server_running():
        click.echo("PCLink is not running. Start it first to get a QR code.", err=True)
        return

    try:
        # Get QR payload directly from the running server via control API
        response = requests.get(f"{CONTROL_API_URL}/qr-data", timeout=5)
        response.raise_for_status()
        qr_data = response.json().get("qr_data")

        if not qr_data:
            click.echo("Failed to retrieve QR code data from server.", err=True)
            return

        click.echo("Scan the QR code below with the PCLink mobile app:")
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
        except Exception:
            # Fallback for non-TTY environments (SSH, pipes, etc.)
            click.echo("(QR code display not available in this terminal)")
            click.echo("")
            click.echo("QR Code Data (for manual entry):")
            click.echo(qr_data)

    except requests.RequestException as e:
        click.echo(f"Failed to fetch QR code data from server: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@cli.command()
def setup():
    """Complete initial password setup for web UI."""
    if web_auth_manager.is_setup_completed():
        click.echo("Setup already completed. Use the web UI to change your password.")
        return

    click.echo("=== PCLink Initial Setup ===")
    click.echo("")
    click.echo("Create a password for the web UI (minimum 8 characters)")

    password = click.prompt("Password", hide_input=True)
    confirm_password = click.prompt("Confirm password", hide_input=True)

    if len(password) < 8:
        click.echo("Error: Password must be at least 8 characters long.", err=True)
        return

    if password != confirm_password:
        click.echo("Error: Passwords do not match.", err=True)
        return

    if web_auth_manager.setup_password(password):
        click.echo("")
        click.echo("✓ Password setup completed successfully!")
        click.echo("")
        click.echo("You can now:")
        click.echo("  1. Start PCLink: pclink start")
        click.echo("  2. Access web UI: https://localhost:38080/ui/")
        click.echo("  3. View pairing info: pclink pair")
    else:
        click.echo("Error: Failed to setup password.", err=True)


@cli.command()
def pair():
    """Display pairing information for mobile devices."""
    if not web_auth_manager.is_setup_completed():
        click.echo("Error: Setup not completed. Run 'pclink setup' first.", err=True)
        return

    if not is_server_running():
        click.echo(
            "Error: PCLink is not running. Start it with 'pclink start'.", err=True
        )
        return

    # Prompt for password to verify identity
    password = click.prompt("Enter your web UI password", hide_input=True)

    # Validate password
    if not web_auth_manager.verify_password(password):
        click.echo("Error: Incorrect password.", err=True)
        return

    try:
        # Get pairing data from server
        response = requests.get(f"{CONTROL_API_URL}/qr-data", timeout=5)
        response.raise_for_status()
        qr_data = response.json().get("qr_data")

        if not qr_data:
            click.echo("Failed to retrieve pairing data from server.", err=True)
            return

        # Display pairing information
        click.echo("")
        click.echo("=== PCLink Pairing Information ===")
        click.echo("")

        # Try to display QR code
        if qrcode:
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
                click.echo("(QR code display not available in this terminal)")
                click.echo("")

        # Always show manual pairing data
        click.echo("Manual Pairing Data:")
        click.echo(qr_data)
        click.echo("")
        click.echo(
            "Scan the QR code or manually enter the data above in the PCLink mobile app."
        )

    except requests.RequestException as e:
        click.echo(f"Failed to fetch pairing data: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@click.group()
def startup():
    """Manage auto-start on system login."""


@startup.command()
def enable():
    """Enable 'Start at system startup'."""
    try:
        startup_manager = StartupManager()
        if startup_manager.enable():
            config_manager.set("auto_start", True)
            click.echo("PCLink will now start automatically at system startup.")
        else:
            click.echo("Failed to enable auto-start.", err=True)
    except Exception as e:
        click.echo(f"Error: Could not enable startup: {e}", err=True)


@startup.command()
def disable():
    """Disable 'Start at system startup'."""
    try:
        startup_manager = StartupManager()
        if startup_manager.disable():
            config_manager.set("auto_start", False)
            click.echo("PCLink will no longer start automatically at system startup.")
        else:
            click.echo("Failed to disable auto-start.", err=True)
    except Exception as e:
        click.echo(f"Error: Could not disable startup: {e}", err=True)


@click.group()
def tray():
    """Enable or disable the system tray icon."""


@tray.command(name="enable")
def enable_tray():
    """Enable the system tray icon on next start."""
    config_manager.set("enable_tray_icon", True)
    click.echo(
        "System tray icon has been enabled. Please restart PCLink for the change to take effect."
    )


@tray.command(name="disable")
def disable_tray():
    """Disable the system tray icon on next start."""
    config_manager.set("enable_tray_icon", False)
    click.echo(
        "System tray icon has been disabled. PCLink will run headless on next start."
    )
    click.echo("Use 'pclink stop' to shut it down.")


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


@cli.group(name="pair")
def pair_group():
    """Manage device pairing requests (Headless Mode)."""
    pass


@pair_group.command(name="list")
def list_pairings():
    """List all pending pairing requests."""
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)

    if not requests_list:
        click.echo("No pending pairing requests.")
        return

    click.echo(f"{'#':<3} | {'Device':<20} | {'IP':<15} | {'Platform'}")
    click.echo("-" * 60)
    for idx, req in enumerate(requests_list, 1):
        click.echo(
            f"{idx:<3} | {req['device_name']:<20} | {req['ip']:<15} | {req['platform']}"
        )


@pair_group.command(name="approve")
@click.argument("id_or_idx", required=False)
def approve_pairing(id_or_idx: str = None):
    """Approve a request by ID or index from 'list'."""
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)
    target_id = None

    if not requests_list:
        click.echo("No pending pairing requests.")
        return

    if not id_or_idx:
        list_pairings()
        val = click.prompt("Select request number to APPROVE", type=int)
        if 0 < val <= len(requests_list):
            target_id = requests_list[val - 1]["pairing_id"]
    elif id_or_idx.isdigit():
        idx = int(id_or_idx)
        if 0 < idx <= len(requests_list):
            target_id = requests_list[idx - 1]["pairing_id"]
    else:
        target_id = id_or_idx

    if not target_id:
        click.echo("Error: Invalid selection.")
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
            click.echo(
                click.style(f"✓ Approved device {target_id}.", fg="green", bold=True)
            )
        else:
            click.echo(f"Failed: {response.text}")
    except Exception as e:
        click.echo(f"Error: {e}")


@pair_group.command(name="deny")
@click.argument("id_or_idx", required=False)
def deny_pairing(id_or_idx: str = None):
    """Deny a request by ID or index from 'list'."""
    port = config_manager.get("server_port", 38080)
    requests_list = _get_pending_pairings(port)
    target_id = None

    if not requests_list:
        click.echo("No pending pairing requests.")
        return

    if not id_or_idx:
        list_pairings()
        val = click.prompt("Select request number to DENY", type=int)
        if 0 < val <= len(requests_list):
            target_id = requests_list[val - 1]["pairing_id"]
    elif id_or_idx.isdigit():
        idx = int(id_or_idx)
        if 0 < idx <= len(requests_list):
            target_id = requests_list[idx - 1]["pairing_id"]
    else:
        target_id = id_or_idx

    if not target_id:
        click.echo("Error: Invalid selection.")
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
            click.echo(
                click.style(f"✗ Denied device {target_id}.", fg="red", bold=True)
            )
        else:
            click.echo(f"Failed: {response.text}")
    except Exception as e:
        click.echo(f"Error: {e}")


# Permission Roles for CLI
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
    ],
    "viewer": ["files_browse", "info", "apps"],
    "media": ["media", "volume", "info", "apps"],
    "remote": ["mouse", "keyboard", "screenshot", "info", "volume"],
    "none": [],
}


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


@cli.group(name="device")
def device_group():
    """Manage paired devices and permissions."""
    pass


@device_group.command(name="list")
def list_devices():
    """List all paired devices."""
    port = config_manager.get("server_port", 38080)
    data = _get_api_data(f"https://localhost:{port}/ui/devices")
    if not data or not data.get("devices"):
        click.echo("No paired devices found.")
        return

    click.echo(
        f"{'#':<3} | {'Device':<20} | {'IP':<15} | {'Platform':<10} | {'Last Seen'}"
    )
    click.echo("-" * 75)
    for idx, d in enumerate(data["devices"], 1):
        click.echo(
            f"{idx:<3} | {d['name']:<20} | {d['ip']:<15} | {d['platform']:<10} | {d['last_seen']}"
        )


@device_group.command(name="revoke")
@click.argument("id_or_idx")
def revoke_device(id_or_idx: str):
    """Kick a device and unpair it."""
    port = config_manager.get("server_port", 38080)
    target_id = id_or_idx
    if id_or_idx.isdigit():
        data = _get_api_data(f"https://localhost:{port}/ui/devices")
        if data and 0 < int(id_or_idx) <= len(data["devices"]):
            target_id = data["devices"][int(id_or_idx) - 1]["id"]

    if _post_api_data(
        f"https://localhost:{port}/ui/devices/revoke", params={"device_id": target_id}
    ):
        click.echo(click.style(f"✓ Device {target_id} revoked.", fg="green", bold=True))
    else:
        click.echo("Error: Could not revoke device.")


@device_group.command(name="ban")
@click.argument("id_or_idx")
def ban_device(id_or_idx: str):
    """Permanently ban a device's hardware ID."""
    port = config_manager.get("server_port", 38080)
    target_id = id_or_idx
    if id_or_idx.isdigit():
        data = _get_api_data(f"https://localhost:{port}/ui/devices")
        if data and 0 < int(id_or_idx) <= len(data["devices"]):
            target_id = data["devices"][int(id_or_idx) - 1]["id"]

    if _post_api_data(
        f"https://localhost:{port}/ui/devices/ban", params={"device_id": target_id}
    ):
        click.echo(
            click.style(
                f"✓ Device {target_id} banned permanently.", fg="red", bold=True
            )
        )
    else:
        click.echo("Error: Could not ban device.")


@device_group.command(name="perm")
@click.argument("id_or_idx")
@click.argument("role", type=click.Choice(list(PERM_ROLES.keys())))
def update_perms(id_or_idx: str, role: str):
    """Update device permissions using a role: admin, viewer, media, remote, none."""
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
        click.echo(
            click.style(
                f"✓ Role '{role}' applied to {target_id}.", fg="blue", bold=True
            )
        )
    else:
        click.echo("Error: Could not update permissions.")


@device_group.command(name="blacklist")
def list_blacklist():
    """List all hardware-banned IDs."""
    port = config_manager.get("server_port", 38080)
    data = _get_api_data(f"https://localhost:{port}/ui/devices/blacklist")
    if not data or not data.get("blacklist"):
        click.echo("Blacklist is empty.")
        return

    click.echo(f"{'#':<3} | {'Hardware ID':<40} | {'Reason'}")
    click.echo("-" * 65)
    for idx, (hwid, reason) in enumerate(data["blacklist"].items(), 1):
        click.echo(f"{idx:<3} | {hwid:<40} | {reason}")


@device_group.command(name="unban")
@click.argument("hwid_or_idx")
def unban_device(hwid_or_idx: str):
    """Remove a hardware ID from the blacklist."""
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
        click.echo(
            click.style(f"✓ Hardware {target_hwid} unbanned.", fg="green", bold=True)
        )
    else:
        click.echo("Error: Could not unban hardware.")


@cli.command(name="fix-wayland")
def fix_wayland():
    """Fix mouse/keyboard issues on Wayland by configuring uinput."""
    if sys.platform != "linux":
        click.echo("This command is only for Linux systems running Wayland.")
        return

    from .core.wayland_utils import (
        check_uinput_access,
        is_wayland,
        setup_uinput_permissions,
    )

    if not is_wayland():
        click.echo(
            "Wayland not detected. This fix is specifically for Wayland sessions."
        )
        if not click.confirm("Do you want to continue anyway?"):
            return

    if check_uinput_access():
        click.echo("✓ You already have write access to /dev/uinput.")
        click.echo("If input still doesn't work, re-open the mobile app and try again.")
        return

    click.echo("--- Wayland Input Fix ---")
    click.echo(
        "To fix mouse/keyboard, PCLink needs permission to create virtual devices."
    )
    click.echo("Run the following command to grant access (requires sudo):")
    click.echo("")
    click.echo(click.style(setup_uinput_permissions(), fg="yellow", bold=True))
    click.echo("")
    click.echo(
        "After running the command, you MUST logout and login again (or restart) for group changes to take effect."
    )


cli.add_command(startup)
cli.add_command(tray)

if __name__ == "__main__":
    cli()

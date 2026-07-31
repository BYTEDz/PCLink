# filepath: src/pclink/cli/commands/server.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys
import time
import subprocess
import gettext
import click
import requests

from ...core import constants
from ...core.version import __version__
from ...core.web_auth import web_auth_manager
from ..helpers import (
    CONTROL_API_URL,
    is_server_running,
    _start_server_process,
    _open_browser,
    _wait_for_condition,
)

_ = gettext.gettext


@click.command(help=_("Start the PCLink background daemon."))
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


@click.command(help=_("Stop the active PCLink daemon."))
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


@click.command(help=_("Restart the active PCLink daemon."))
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


@click.command(help=_("Display the current operational status of the PCLink daemon."))
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


@click.command(name="ui", help=_("Launch the Web UI dashboard in the default browser."))
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


@click.command(help=_("Display or continuously follow the application log file."))
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


@click.command(help=_("Initialize the primary administrator password for the Web UI."))
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


@click.command(
    name="update", help=_("Check for and install PCLink application updates.")
)
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
    from ...core.update_checker import UpdateChecker

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

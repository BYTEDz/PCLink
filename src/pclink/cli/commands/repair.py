# filepath: src/pclink/cli/commands/repair.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import getpass
import gettext
import sys
import click

_ = gettext.gettext


@click.group(
    name="repair", help=_("Diagnostic and repair utilities (diagnose, fix, wayland).")
)
def repair_group():
    pass


@repair_group.command(
    help=_("Execute diagnostic checks on system configuration and network state.")
)
def diagnose():
    from ...services.repair_service import repair_service

    click.secho(_("Initiating system diagnostics..."), fg="cyan")
    results = asyncio.run(repair_service.run_diagnostics())

    for component, res in results.items():
        msg, status = res.get("message"), res.get("status")
        color = (
            "green" if status == "ok" else "yellow" if status == "warning" else "red"
        )
        symbol = "✓" if status == "ok" else "⚠" if status == "warning" else "✗"
        click.secho(_("{} {}: {}").format(symbol, component.upper(), msg), fg=color)


@repair_group.command(
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
    from ...services.repair_service import repair_service

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


@repair_group.command(
    name="wayland", help=_("Resolve input emulation issues in Wayland environments.")
)
def repair_wayland():
    if sys.platform != "linux":
        return click.secho(
            _("This utility is exclusively for Linux systems operating under Wayland."),
            fg="red",
            err=True,
        )

    from ...core.wayland_utils import (
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

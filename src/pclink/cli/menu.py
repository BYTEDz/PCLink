# filepath: src/pclink/cli/menu.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import click

try:
    import questionary
except ImportError:
    questionary = None

from ..core.config import config_manager

# Import commands to execute them via context (ctx.invoke)
from .commands.server import (
    start,
    stop,
    restart,
    status,
    ui,
    logs,
    setup,
    update_command,
)
from .commands.devices import (
    list_devices,
    list_requests,
    approve_pairing,
    reject_pairing,
    revoke_device,
    ban_device,
    unban_device,
    list_blacklist,
    get_qr,
    _get_pending_pairings,
)
from .commands.config import config_set_autostart, config_set_tray
from .commands.repair import diagnose, run_repair, repair_wayland

_ = gettext.gettext


def _run_interactive_menu(title, choices, action_map):
    """Shared handler for processing interactive menus."""
    while True:
        action = questionary.select(title, choices=choices).ask()
        if action in ("back", "exit", None):
            break
        if action in action_map:
            action_map[action]()
        click.echo("")


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

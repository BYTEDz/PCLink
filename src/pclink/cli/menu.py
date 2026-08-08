# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys
import gettext
import click

try:
    import questionary
except ImportError:
    questionary = None

from ..core.config import config_manager
from ..core.version import version_info
from ..core.web_auth import web_auth_manager
from .helpers import PCLINK_CLI_STYLE

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
    about_command,
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
    update_perms,
    device_policy,
    _get_pending_pairings,
)
from .commands.config import (
    config_set_autostart,
    config_set_tray,
    list_services,
    edit_services_interactive,
)
from .commands.repair import diagnose, run_repair, repair_wayland

_ = gettext.gettext


def _print_menu_header(update_version=None):
    """Renders the ASCII logo banner, version tag, and update indicator at the top of the menu."""
    click.clear()
    click.secho(
        r"""  ____   ____ _     _       _
 |  _ \ / ___| |   (_)_ __ | | __
 | |_) | |   | |   | | '_ \| |/ /
 |  __/| |___| |___| | | | |   <
 |_|    \____|_____|_|_| |_|_|\_\
""",
        fg="cyan",
        bold=True,
    )
    click.secho(
        f"  {version_info.product_name} v{version_info.version}",
        fg="green",
        bold=True,
    )
    if update_version:
        click.secho(
            _(
                "  ★ UPDATE AVAILABLE: v{} (Select 'Check for Updates' to install)\n"
            ).format(update_version),
            fg="yellow",
            bold=True,
        )
    else:
        click.echo("")


def _run_interactive_menu(title, choices, action_map):
    """Shared handler for processing interactive submenus with automatic screen clearing."""
    while True:
        _print_menu_header()
        action = questionary.select(
            title, choices=choices, style=PCLINK_CLI_STYLE
        ).ask()
        if action in ("back", "exit", None):
            click.clear()
            return "NO_PAUSE"
        if action in action_map:
            click.clear()
            res = action_map[action]()
            if res != "NO_PAUSE" and sys.stdout.isatty():
                click.pause(_("\nPress Any Key to Return to Menu..."))


def _pending_requests_menu(ctx):
    if not _get_pending_pairings(config_manager.get("server_port", 38080)):
        click.secho(_("No pending pairing requests found."), fg="yellow")
        return

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
    return _run_interactive_menu(_("Pending Request Action:"), choices, action_map)


def _device_menu(ctx):
    def _prompt_and_run(cmd, prompt_msg, list_cmd=None, **kwargs):
        if list_cmd:
            ctx.invoke(list_cmd, all=False) if list_cmd == list_devices else ctx.invoke(
                list_cmd
            )
        val = questionary.text(prompt_msg, style=PCLINK_CLI_STYLE).ask()
        if val:
            ctx.invoke(cmd, id_or_idx=val, **kwargs)

    choices = [
        questionary.Choice(_("List Paired Devices"), value="list"),
        questionary.Choice(_("Pending Pairing Requests"), value="requests"),
        questionary.Choice(_("Get Pairing QR Code"), value="get_qr"),
        questionary.Choice(_("Default New-Device Policy"), value="policy"),
        questionary.Choice(_("Edit Device Permissions"), value="perm_checkbox"),
        questionary.Choice(_("Revoke Device Access"), value="revoke"),
        questionary.Choice(_("Ban Device"), value="ban"),
        questionary.Choice(_("Unban Device"), value="unban"),
        questionary.Choice(_("List Blacklist"), value="blacklist"),
        questionary.Choice(_("Back to Main Menu"), value="back"),
    ]
    action_map = {
        "list": lambda: ctx.invoke(list_devices, all=False),
        "requests": lambda: _pending_requests_menu(ctx),
        "get_qr": lambda: ctx.invoke(get_qr),
        "policy": lambda: ctx.invoke(device_policy, edit=True),
        "perm_checkbox": lambda: _prompt_and_run(
            update_perms,
            _(
                "Enter Device ID or Index to Edit Permissions (or press Enter to cancel):"
            ),
            list_devices,
            role=None,
        ),
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
    return _run_interactive_menu(_("Manage Devices & Pairing:"), choices, action_map)


def _service_menu(ctx):
    choices = [
        questionary.Choice(_("List Global Service Status"), value="list"),
        questionary.Choice(_("Edit Global Feature Switches"), value="edit"),
        questionary.Choice(_("Back to Main Menu"), value="back"),
    ]
    action_map = {
        "list": lambda: ctx.invoke(list_services),
        "edit": lambda: ctx.invoke(edit_services_interactive),
    }
    return _run_interactive_menu(_("Global Feature Switches:"), choices, action_map)


def _config_menu(ctx):
    choices = [
        questionary.Choice(_("Enable Autostart"), value="auto_en"),
        questionary.Choice(_("Disable Autostart"), value="auto_dis"),
        questionary.Choice(_("Enable System Tray"), value="tray_en"),
        questionary.Choice(_("Disable System Tray"), value="tray_dis"),
        questionary.Choice(_("Global Feature Switches"), value="services"),
        questionary.Choice(_("Back to Main Menu"), value="back"),
    ]
    action_map = {
        "auto_en": lambda: ctx.invoke(config_set_autostart, state="enable"),
        "auto_dis": lambda: ctx.invoke(config_set_autostart, state="disable"),
        "tray_en": lambda: ctx.invoke(config_set_tray, state="enable"),
        "tray_dis": lambda: ctx.invoke(config_set_tray, state="disable"),
        "services": lambda: _service_menu(ctx),
    }
    return _run_interactive_menu(_("Configuration:"), choices, action_map)


def _repair_menu(ctx):
    def _fix_port():
        strat = questionary.select(
            _("Select Port Resolution Strategy:"),
            choices=[
                questionary.Choice(_("Kill Conflicting Process"), value="kill"),
                questionary.Choice(_("Auto-Assign New Port"), value="change"),
                questionary.Choice(_("Cancel"), value="cancel"),
            ],
            style=PCLINK_CLI_STYLE,
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
    return _run_interactive_menu(_("Repair Center:"), choices, action_map)


def _run_cmd_no_pause(ctx, cmd, **kwargs):
    """Executes a daemon operation command and automatically returns to menu without keypress pause."""
    import time

    ctx.invoke(cmd, **kwargs)
    time.sleep(1)
    return "NO_PAUSE"


def launch_interactive_menu(ctx):
    if not questionary:
        click.secho(
            _("Interactive mode requires 'questionary' (pip install questionary)."),
            fg="red",
            err=True,
        )
        return ctx.invoke(start)

    is_advanced_mode = False

    # Perform lightweight update availability probe for CLI banner
    update_info = None
    try:
        from ..core.update_checker import UpdateChecker

        update_info = UpdateChecker().check_for_updates(timeout=2)
    except Exception:
        pass

    latest_version = update_info.get("version") if update_info else None

    while True:
        update_label = (
            _("Check for Updates [UPDATE AVAILABLE: v{}]").format(latest_version)
            if latest_version
            else _("Check for Updates")
        )

        if is_advanced_mode:
            choices = [
                questionary.Choice(_("Start PCLink Daemon"), value="start"),
                questionary.Choice(_("Stop PCLink Daemon"), value="stop"),
                questionary.Choice(_("Restart PCLink Daemon"), value="restart"),
                questionary.Choice(_("Status"), value="status"),
                questionary.Choice(_("Open Web UI"), value="ui"),
                questionary.Choice(_("Manage Devices & Pairing"), value="devices"),
                questionary.Choice(_("Global Feature Switches"), value="services"),
                questionary.Choice(_("Configuration"), value="config"),
                questionary.Choice(_("Repair Center"), value="repair"),
                questionary.Choice(_("View Logs"), value="logs"),
                questionary.Choice(update_label, value="update"),
                questionary.Choice(_("Initial Admin Setup"), value="setup"),
                questionary.Choice(_("About PCLink"), value="about"),
                questionary.Choice(_("Lock Advanced Mode"), value="lock_advanced"),
                questionary.Choice(_("Exit"), value="exit"),
            ]
        else:
            choices = [
                questionary.Choice(_("Start PCLink Daemon"), value="start"),
                questionary.Choice(_("Stop PCLink Daemon"), value="stop"),
                questionary.Choice(_("Restart PCLink Daemon"), value="restart"),
                questionary.Choice(_("Status"), value="status"),
                questionary.Choice(_("Open Web UI"), value="ui"),
                questionary.Choice(_("View Logs"), value="logs"),
                questionary.Choice(update_label, value="update"),
                questionary.Choice(_("About PCLink"), value="about"),
                questionary.Choice(
                    _("Unlock Advanced Mode (Password Required)"),
                    value="unlock_advanced",
                ),
                questionary.Choice(_("Exit"), value="exit"),
            ]

        action_map = {
            "start": lambda: _run_cmd_no_pause(ctx, start),
            "stop": lambda: _run_cmd_no_pause(ctx, stop),
            "restart": lambda: _run_cmd_no_pause(ctx, restart),
            "status": lambda: ctx.invoke(status),
            "ui": lambda: ctx.invoke(ui),
            "logs": lambda: ctx.invoke(logs, follow=False),
            "update": lambda: ctx.invoke(update_command, force=False, yes=False),
            "about": lambda: ctx.invoke(about_command),
            "setup": lambda: ctx.invoke(setup),
            "devices": lambda: _device_menu(ctx),
            "services": lambda: _service_menu(ctx),
            "config": lambda: _config_menu(ctx),
            "repair": lambda: _repair_menu(ctx),
        }

        _print_menu_header(latest_version)
        if is_advanced_mode:
            click.secho(_("  [ADVANCED ADMIN MODE ACTIVE]\n"), fg="yellow", bold=True)
        else:
            click.secho(_("  [BASIC MODE ACTIVE]\n"), fg="cyan", bold=True)

        action = questionary.select(
            _("Main Menu:"), choices=choices, style=PCLINK_CLI_STYLE
        ).ask()

        if action in ("exit", None):
            click.clear()
            break

        if action == "unlock_advanced":
            click.clear()
            if not web_auth_manager.is_setup_completed():
                click.secho(
                    _(
                        "Administrator password setup is incomplete. Execute 'Initial Admin Setup' first."
                    ),
                    fg="yellow",
                    bold=True,
                )
            else:
                pwd = click.prompt(_("Enter Master Password"), hide_input=True)
                if web_auth_manager.verify_password(pwd):
                    is_advanced_mode = True
                    click.secho(
                        _("✓ Advanced Admin Mode Unlocked!"), fg="green", bold=True
                    )
                else:
                    click.secho(
                        _("✗ Authentication failed. Incorrect password."),
                        fg="red",
                        err=True,
                    )
            if sys.stdout.isatty():
                click.pause(_("\nPress Any Key to Continue..."))
            continue

        if action == "lock_advanced":
            is_advanced_mode = False
            click.clear()
            click.secho(
                _("Advanced Mode Locked. Switched to Basic Mode."), fg="cyan", bold=True
            )
            if sys.stdout.isatty():
                click.pause(_("\nPress Any Key to Continue..."))
            continue

        if action in action_map:
            click.clear()
            res = action_map[action]()
            if res != "NO_PAUSE" and sys.stdout.isatty():
                click.pause(_("\nPress Any Key to Return to Menu..."))

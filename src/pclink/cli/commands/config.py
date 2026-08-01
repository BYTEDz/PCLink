# filepath: src/pclink/cli/commands/config.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import click
import gettext
from ...core.config import config_manager
from ...core.startup import StartupManager
from ..helpers import (
    PCLINK_CLI_STYLE,
    _post_api_data,
    _print_table,
    is_server_running,
)

try:
    import questionary
except ImportError:
    questionary = None

_ = gettext.gettext

SERVICE_LABELS = {
    "files_read": _("File Access (Read)"),
    "files_write": _("File Access (Write)"),
    "input": _("Remote Input & Clipboard"),
    "media": _("Media & Volume Control"),
    "apps": _("Applications"),
    "processes": _("Processes"),
    "power": _("Power Control"),
    "info": _("System Status"),
    "screenshot": _("Screen Capture"),
    "macros": _("Macros"),
    "extensions": _("Server Extensions"),
    "desktop_streaming": _("Desktop Streaming"),
    "terminal": _("Terminal & Shell (High Risk)"),
}


@click.group(name="config", help=_("Manage PCLink config (set autostart, set tray)."))
def config_group():
    pass


@config_group.group(name="set", help=_("Modify specific configuration keys."))
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


# --- Layer 1: Global Services / Kill Switches ---


@click.group(
    name="service",
    help=_(
        "Layer 1: Manage global service kill switches (enable/disable features server-wide)."
    ),
)
def service_group():
    pass


@service_group.command(
    name="list", help=_("List all global service kill switches and their status.")
)
def list_services():
    services = config_manager.get("services", {})
    if not services:
        return click.secho(_("No services configured."), fg="yellow")

    rows = []
    # Always iterate strictly over the 13 canonical service keys
    for idx, name in enumerate(SERVICE_LABELS.keys(), 1):
        enabled = services.get(name, True)
        status_str = _("ENABLED") if enabled else _("DISABLED")
        label = SERVICE_LABELS.get(name, name)
        rows.append([idx, name, label, status_str])

    _print_table(
        [_("ID"), _("Service"), _("Description"), _("Global Status")],
        rows,
        [3, 20, 32, 15],
    )


@service_group.command(
    name="toggle", help=_("Toggle a specific global service on or off.")
)
@click.argument("service_name")
@click.option(
    "--enable/--disable",
    default=None,
    help=_("Explicitly enable or disable the service."),
)
def toggle_service(service_name: str, enable: bool = None):
    port = config_manager.get("server_port", 38080)
    services = config_manager.get("services", {})

    if service_name not in SERVICE_LABELS:
        return click.secho(
            _("Error: Service '{}' not found.").format(service_name), fg="red", err=True
        )

    new_state = (not services.get(service_name, True)) if enable is None else enable

    success = False
    if is_server_running():
        success = _post_api_data(
            f"https://127.0.0.1:{port}/ui/services/toggle",
            json={"name": service_name, "enabled": new_state},
        )

    if not success:
        services_copy = services.copy()
        services_copy[service_name] = new_state
        config_manager.set("services", services_copy)
        success = True

    if success:
        status_msg = _("enabled") if new_state else _("disabled")
        click.secho(
            _("✓ Global service '{}' has been {}.").format(service_name, status_msg),
            fg="green" if new_state else "yellow",
            bold=True,
        )
    else:
        click.secho(_("Error: Failed to toggle global service."), fg="red", err=True)


@service_group.command(
    name="edit",
    help=_("Interactively toggle global service kill switches using checkboxes."),
)
def edit_services_interactive():
    if not questionary:
        return click.secho(
            _("Interactive mode requires 'questionary' (pip install questionary)."),
            fg="red",
            err=True,
        )

    services = config_manager.get("services", {})
    choices = [
        questionary.Choice(
            title=f"{SERVICE_LABELS.get(s, s)} [{s}]",
            value=s,
            checked=services.get(s, True),
        )
        for s in SERVICE_LABELS.keys()
    ]

    selected = questionary.checkbox(
        _("Select global services to ENABLE on server (Layer 1 Kill Switches):"),
        choices=choices,
        style=PCLINK_CLI_STYLE,
    ).ask()

    if selected is None:
        return

    port = config_manager.get("server_port", 38080)
    updated_services = {s: (s in selected) for s in SERVICE_LABELS.keys()}

    for s_name, is_en in updated_services.items():
        if is_server_running():
            _post_api_data(
                f"https://127.0.0.1:{port}/ui/services/toggle",
                json={"name": s_name, "enabled": is_en},
            )

    config_manager.set("services", updated_services)
    click.secho(
        _("✓ Global service kill switches updated successfully."), fg="green", bold=True
    )

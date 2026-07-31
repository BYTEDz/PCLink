# filepath: src/pclink/cli/commands/config.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import click
import gettext
from ...core.config import config_manager
from ...core.startup import StartupManager

_ = gettext.gettext


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

# filepath: src/pclink/cli/__init__.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys
import click

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
    device_group,
    get_qr,
    device_policy,
    update_perms,
)
from .commands.config import config_group, service_group
from .commands.repair import repair_group
from .menu import launch_interactive_menu


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """PCLink Server Control Interface."""
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty():
            launch_interactive_menu(ctx)
        else:
            ctx.invoke(start)


# Register top-level commands (Server operations)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(restart)
cli.add_command(status)
cli.add_command(ui)
cli.add_command(ui, name="web")
cli.add_command(ui, name="dashboard")
cli.add_command(logs)
cli.add_command(setup)
cli.add_command(update_command, name="update")
cli.add_command(about_command, name="about")
cli.add_command(about_command, name="info")
cli.add_command(about_command, name="version")

# Convenient Top-Level Shortcuts
cli.add_command(get_qr, name="qr")
cli.add_command(get_qr, name="pair")
cli.add_command(device_policy, name="policy")
cli.add_command(update_perms, name="perms")

# Register command groups
cli.add_command(device_group, name="device")
cli.add_command(config_group, name="config")
cli.add_command(service_group, name="service")
cli.add_command(repair_group, name="repair")

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import shutil
import click
import requests

from ...core.config import config_manager
from ...core.web_auth import web_auth_manager
from ..helpers import (
    CONTROL_API_URL,
    PCLINK_CLI_STYLE,
    _get_api_data,
    _post_api_data,
    _print_table,
    _resolve_target_id,
    is_server_running,
)

try:
    import qrcode
    from qrcode import constants as qr_constants
except ImportError:
    qrcode = None

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


def _print_compact_qr(matrix):
    """Renders a compact terminal QR code using Unicode half-block characters (cuts height in half)."""
    total_rows = len(matrix)
    total_cols = len(matrix[0]) if total_rows > 0 else 0

    lines = []
    for y in range(0, total_rows, 2):
        line = []
        for x in range(total_cols):
            top = matrix[y][x]
            bottom = matrix[y + 1][x] if y + 1 < total_rows else False

            if top and bottom:
                line.append("█")
            elif top and not bottom:
                line.append("▀")
            elif not top and bottom:
                line.append("▄")
            else:
                line.append(" ")
        lines.append("".join(line))

    for line_str in lines:
        click.secho(f"  {line_str}")


def _get_pending_pairings(port: int):
    """Helper to fetch pending pairings from the local server or fallback directly to SQLite."""
    if is_server_running():
        data = _get_api_data(f"https://127.0.0.1:{port}/ui/pairing/list")
        if data and "requests" in data:
            return data.get("requests", [])

    from ...core.device_manager import device_manager

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
                style=PCLINK_CLI_STYLE,
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
        from ...core.device_manager import device_manager

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


@click.group(
    name="device",
    help=_(
        "Manage devices (list, requests, approve, reject, perm, policy, get-qr, ban, etc)."
    ),
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
        from ...core.device_manager import device_manager

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
        from ...core.device_manager import device_manager

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
        from ...core.device_manager import device_manager

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
        from ...core.device_manager import device_manager

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
        from ...core.device_manager import device_manager

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


# --- Device Access & Permissions ---


@device_group.command(
    name="perm",
    help=_("Assign permissions to a specific device (role or checkbox picker)."),
)
@click.argument("id_or_idx")
@click.argument("role", type=click.Choice(list(PERM_ROLES.keys())), required=False)
def update_perms(id_or_idx: str, role: str = None):
    port = config_manager.get("server_port", 38080)
    target_id = _resolve_target_id(id_or_idx, "devices", "devices", "id")

    if role:
        perms = PERM_ROLES.get(role, [])
    else:
        if not questionary:
            return click.secho(
                _(
                    "Error: Specify a role ({}) or install 'questionary' for interactive selection."
                ).format(", ".join(PERM_ROLES.keys())),
                fg="red",
                err=True,
            )

        from ...core.device_manager import device_manager

        device = device_manager.get_device_by_id(target_id)
        current_perms = set(device.permissions) if device else set()
        global_services = config_manager.get("services", {})

        choices = []
        for s_key, label in SERVICE_LABELS.items():
            is_disabled_globally = not global_services.get(s_key, True)
            display_title = f"{label} [{s_key}]"
            if is_disabled_globally:
                display_title += _(" (DISABLED GLOBALLY AT FEATURE SWITCH)")

            choices.append(
                questionary.Choice(
                    title=display_title,
                    value=s_key,
                    checked=(s_key in current_perms),
                )
            )

        selected = questionary.checkbox(
            _("Select permissions for device {}:").format(target_id),
            choices=choices,
            style=PCLINK_CLI_STYLE,
        ).ask()

        if selected is None:
            return
        perms = selected

    success = (
        _post_api_data(
            f"https://127.0.0.1:{port}/ui/devices/{target_id}/permissions/bulk",
            json={"permissions": perms},
        )
        if is_server_running()
        else False
    )
    if not success:
        from ...core.device_manager import device_manager

        device = device_manager.get_device_by_id(target_id)
        if device:
            device.permissions = perms
            device_manager._save_device(device)
            success = True

    if success:
        click.secho(
            _("✓ Permissions updated successfully for device {}.").format(target_id),
            fg="cyan",
            bold=True,
        )
    else:
        click.secho(
            _("Error: Failed to modify device permissions."), fg="red", err=True
        )


# --- Default Device Permission Policy ---


@device_group.command(
    name="policy",
    help=_("View or edit default permissions assigned to newly paired devices."),
)
@click.option(
    "--edit", "-e", is_flag=True, help=_("Interactively edit default device policy.")
)
def device_policy(edit: bool = False):
    port = config_manager.get("server_port", 38080)
    current_defaults = config_manager.get("default_device_permissions", [])

    if not edit:
        click.secho(
            _("=== Default New-Device Permission Policy ==="),
            fg="cyan",
            bold=True,
        )
        if not current_defaults:
            click.secho(
                _("No default permissions set (new devices will have 0 permissions)."),
                fg="yellow",
            )
        else:
            rows = [
                [idx, perm, SERVICE_LABELS.get(perm, perm)]
                for idx, perm in enumerate(current_defaults, 1)
            ]
            _print_table(
                [_("ID"), _("Permission Key"), _("Description")], rows, [3, 20, 35]
            )
        click.echo(
            _(
                "\nRun 'pclink device policy --edit' to interactively modify default policy."
            )
        )
        return

    if not questionary:
        return click.secho(
            _("Interactive editing requires 'questionary' (pip install questionary)."),
            fg="red",
            err=True,
        )

    choices = [
        questionary.Choice(
            title=f"{label} [{s_key}]",
            value=s_key,
            checked=(s_key in current_defaults),
        )
        for s_key, label in SERVICE_LABELS.items()
    ]

    selected = questionary.checkbox(
        _("Select default permissions assigned to newly paired devices:"),
        choices=choices,
        style=PCLINK_CLI_STYLE,
    ).ask()

    if selected is None:
        return

    success = False
    if is_server_running():
        success = _post_api_data(
            f"https://127.0.0.1:{port}/settings/defaults/permissions",
            json={"permissions": selected},
        )

    if not success:
        config_manager.set("default_device_permissions", selected)
        success = True

    if success:
        click.secho(
            _("✓ Default new-device permission policy updated."), fg="green", bold=True
        )
    else:
        click.secho(
            _("Error: Failed to save default permission policy."), fg="red", err=True
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

        # Dynamic Quiet Zone & Compact Half-Block Rendering
        term_size = shutil.get_terminal_size((80, 24))
        border_size = 1 if term_size.lines < 30 or term_size.columns < 60 else 2

        qr_obj = qrcode.QRCode(
            error_correction=qr_constants.ERROR_CORRECT_L,
            box_size=1,
            border=border_size,
        )
        qr_obj.add_data(qr_data)
        qr_obj.make(fit=True)

        try:
            # Use compact Unicode half-block rendering (cuts line height in half)
            matrix = qr_obj.get_matrix()
            _print_compact_qr(matrix)
            click.echo("")
        except Exception:
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

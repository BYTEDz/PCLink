# src/pclink/services/repair_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import gc
import json
import logging
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict

import psutil

from ..core import constants
from ..core.config import config_manager
from ..core.device_manager import device_manager

log = logging.getLogger(__name__)
_ = gettext.gettext


class RepairService:
    """Diagnostic, root-cause detection, and automated self-healing service."""

    @staticmethod
    def check_port_availability(port: int) -> dict:
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            s.close()
            return {"status": "ok", "message": _("Port {} is available.").format(port)}
        except OSError as e:
            try:
                res = requests.get(
                    f"https://127.0.0.1:{port}/auth", verify=False, timeout=1
                )
                if "PCLink" in res.text or res.status_code == 200:
                    return {
                        "status": "ok",
                        "message": _("Port {} is correctly bound by PCLink.").format(
                            port
                        ),
                    }
            except Exception:
                try:
                    res2 = requests.get(f"http://127.0.0.1:{port}/auth", timeout=1)
                    if "PCLink" in res2.text or res2.status_code == 200:
                        return {
                            "status": "ok",
                            "message": _(
                                "Port {} is correctly bound by PCLink."
                            ).format(port),
                        }
                except Exception:
                    pass

            return {
                "status": "warning",
                "message": _("Port {} is in use by another application.").format(port),
                "error": str(e),
            }

    @staticmethod
    def check_db_integrity() -> dict:
        if not device_manager.db_path.exists():
            return {"status": "error", "message": _("Database file is missing.")}
        try:
            conn = sqlite3.connect(f"file:{device_manager.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == "ok":
                return {"status": "ok", "message": _("Database is healthy.")}
            else:
                return {
                    "status": "error",
                    "message": _("Database corruption detected."),
                }
        except sqlite3.DatabaseError as e:
            return {"status": "error", "message": _("Database error: {}").format(e)}
        except Exception as e:
            return {"status": "error", "message": _("Unexpected error: {}").format(e)}

    @staticmethod
    def check_config() -> dict:
        if not constants.CONFIG_FILE.exists():
            return {"status": "error", "message": _("Config file is missing.")}
        try:
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                json.load(f)
            return {"status": "ok", "message": _("Config file is valid.")}
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "message": _("Config JSON is invalid: {}").format(e),
            }
        except Exception as e:
            return {"status": "error", "message": _("Config error: {}").format(e)}

    @staticmethod
    def check_firewall() -> dict:
        if sys.platform == "win32":
            try:
                check_cmd = [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "show",
                    "rule",
                    "name=PCLink Server",
                    "dir=in",
                ]
                result = subprocess.run(
                    check_cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
                if "No rules match" in result.stdout:
                    return {
                        "status": "error",
                        "message": _("Windows Firewall rule is missing."),
                    }
                return {"status": "ok", "message": _("Windows Firewall rule exists.")}
            except Exception as e:
                return {
                    "status": "error",
                    "message": _("Failed to check Windows firewall: {}").format(e),
                }
        elif sys.platform.startswith("linux"):
            try:
                result = subprocess.run(
                    ["sudo", "-n", "ufw", "status"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    return {
                        "status": "warning",
                        "message": _("UFW is active, ensure port 38080 is allowed."),
                    }
                return {
                    "status": "ok",
                    "message": _(
                        "Linux firewall check requires manual verification or UFW is inactive."
                    ),
                }
            except Exception:
                return {
                    "status": "ok",
                    "message": _("Linux firewall check requires manual verification."),
                }
        return {
            "status": "ok",
            "message": _("Firewall check not supported on this OS."),
        }

    @staticmethod
    def detect_instability_causes() -> Dict[str, Any]:
        """Deep root-cause analyzer detecting why the server may be unstable or unreachable."""
        causes = []
        severity = "healthy"

        # 1. Memory Pressure
        try:
            mem = psutil.virtual_memory()
            proc = psutil.Process()
            proc_mem_mb = proc.memory_info().rss / 1024 / 1024
            if mem.percent > 92 or proc_mem_mb > 1024:
                severity = "critical" if mem.percent > 96 else "warning"
                causes.append(
                    {
                        "id": "high_memory_pressure",
                        "title": _("High Memory Pressure"),
                        "severity": severity,
                        "description": _(
                            "System memory usage is at {}% with PCLink consuming {} MB."
                        ).format(mem.percent, round(proc_mem_mb, 1)),
                        "recommendation": _(
                            "Trigger memory garbage collection or clear temporary cache."
                        ),
                    }
                )
        except Exception as e:
            log.debug(f"Memory check exception: {e}")

        # 2. File Descriptor Leaks
        try:
            proc = psutil.Process()
            num_fds = len(proc.open_files())
            if num_fds > 500:
                causes.append(
                    {
                        "id": "descriptor_leak",
                        "title": _("High File Descriptor Usage"),
                        "severity": "warning",
                        "description": _(
                            "PCLink currently has {} open file handles."
                        ).format(num_fds),
                        "recommendation": _(
                            "Clean up stale transfer sessions and idle connections."
                        ),
                    }
                )
        except Exception:
            pass

        # 3. Database WAL File Growth
        try:
            wal_file = device_manager.db_path.with_suffix(".db-wal")
            if wal_file.exists():
                wal_size_mb = wal_file.stat().st_size / 1024 / 1024
                if wal_size_mb > 20:
                    causes.append(
                        {
                            "id": "db_wal_bloat",
                            "title": _("Database WAL File Bloat"),
                            "severity": "warning",
                            "description": _(
                                "SQLite WAL journal size is {} MB."
                            ).format(round(wal_size_mb, 1)),
                            "recommendation": _(
                                "Execute WAL checkpoint to flush database write log."
                            ),
                        }
                    )
        except Exception:
            pass

        # 4. Network Interface Reachability
        try:
            from ..core.utils import get_available_ips

            ips = get_available_ips()
            if not ips or ips == ["127.0.0.1"]:
                causes.append(
                    {
                        "id": "network_isolated",
                        "title": _("No Active Network Interface"),
                        "severity": "critical",
                        "description": _(
                            "No non-loopback IPv4 addresses detected. Remote devices cannot connect."
                        ),
                        "recommendation": _(
                            "Check Wi-Fi or Ethernet network connection."
                        ),
                    }
                )
        except Exception:
            pass

        return {
            "timestamp": time.time(),
            "overall_status": severity,
            "detected_causes": causes,
            "total_issues": len(causes),
        }

    @staticmethod
    def auto_heal() -> Dict[str, Any]:
        """Attempts non-destructive automated repairs to resolve instability."""
        repaired_actions = []

        # 1. Force Python Garbage Collection
        collected = gc.collect()
        repaired_actions.append(
            _("Garbage collection executed ({} objects freed).").format(collected)
        )

        # 2. SQLite WAL Checkpoint to shrink WAL journal bloat
        try:
            with sqlite3.connect(device_manager.db_path) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            repaired_actions.append(_("SQLite WAL log checkpointed successfully."))
        except Exception as e:
            log.debug(f"WAL checkpoint failed: {e}")

        # 3. Cleanup Stale Transfer Files
        try:
            from .transfer_service import transfer_service
            import asyncio

            cleaned = asyncio.run(transfer_service.cleanup_stale_sessions(days=1))
            if cleaned > 0:
                repaired_actions.append(
                    _("Purged {} stale transfer files.").format(cleaned)
                )
        except Exception as e:
            log.debug(f"Stale transfer cleanup during auto-heal failed: {e}")

        return {
            "status": "ok",
            "message": _("Self-healing sequence executed successfully."),
            "actions_taken": repaired_actions,
        }

    @staticmethod
    def run_diagnostics() -> dict:
        port = config_manager.get("server_port", 38080)
        return {
            "port": RepairService.check_port_availability(port),
            "db": RepairService.check_db_integrity(),
            "config": RepairService.check_config(),
            "firewall": RepairService.check_firewall(),
        }

    @staticmethod
    def fix_db() -> dict:
        if not device_manager.db_path.exists():
            return {"status": "error", "message": _("No DB to fix.")}
        try:
            backup_path = device_manager.db_path.with_suffix(".db.bak")
            shutil.copy2(device_manager.db_path, backup_path)
            device_manager.db_path.unlink()
            device_manager._init_database()
            return {
                "status": "ok",
                "message": _("Database recreated. Backup saved to {}").format(
                    backup_path
                ),
            }
        except Exception as e:
            return {"status": "error", "message": _("Failed to fix DB: {}").format(e)}

    @staticmethod
    def fix_config() -> dict:
        try:
            backup_path = constants.CONFIG_FILE.with_suffix(".json.bak")
            if constants.CONFIG_FILE.exists():
                shutil.copy2(constants.CONFIG_FILE, backup_path)
                constants.CONFIG_FILE.unlink()
            config_manager.reset_to_defaults()
            return {"status": "ok", "message": _("Config reset to defaults.")}
        except Exception as e:
            return {
                "status": "error",
                "message": _("Failed to fix config: {}").format(e),
            }

    @staticmethod
    def force_repair() -> dict:
        try:
            RepairService.fix_db()
            RepairService.fix_config()
            if constants.UPLOADS_PATH.exists():
                shutil.rmtree(constants.UPLOADS_PATH, ignore_errors=True)
                constants.UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
            if constants.DOWNLOADS_PATH.exists():
                shutil.rmtree(constants.DOWNLOADS_PATH, ignore_errors=True)
                constants.DOWNLOADS_PATH.mkdir(parents=True, exist_ok=True)

            return {
                "status": "ok",
                "message": _("Factory reset complete. System is fresh."),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": _("Force repair failed: {}").format(e),
            }

    @staticmethod
    def fix_firewall(password: str = None) -> dict:
        if sys.platform == "win32":
            try:
                exe_path = sys.executable
                app_name = "PCLink Server"
                add_cmd = [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "add",
                    "rule",
                    f"name={app_name}",
                    "dir=in",
                    "action=allow",
                    f"program={exe_path}",
                    "enable=yes",
                ]
                subprocess.run(
                    add_cmd,
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
                return {"status": "ok", "message": _("Windows Firewall rule added.")}
            except Exception as e:
                return {
                    "status": "error",
                    "message": _("Failed to add firewall rule: {}").format(e),
                }
        elif sys.platform.startswith("linux"):
            port = config_manager.get("server_port", 38080)
            try:
                res = subprocess.run(
                    ["sudo", "-n", "ufw", "allow", f"{port}/tcp"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return {
                        "status": "ok",
                        "message": _("UFW rule added for port {}.").format(port),
                    }
            except Exception:
                pass

            if password:
                try:
                    cmd = f"echo '{password}' | sudo -S ufw allow {port}/tcp"
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        return {
                            "status": "ok",
                            "message": _("UFW rule added for port {}.").format(port),
                        }
                    return {
                        "status": "error",
                        "message": _("UFW command failed: {}").format(result.stderr),
                    }
                except Exception as e:
                    return {"status": "error", "message": str(e)}

            try:
                result = subprocess.run(
                    ["pkexec", "ufw", "allow", f"{port}/tcp"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return {
                        "status": "ok",
                        "message": _(
                            "UFW rule added for port {} via GUI prompt."
                        ).format(port),
                    }
            except FileNotFoundError:
                pass

            return {
                "status": "warning",
                "message": _("Run manually: sudo ufw allow {}/tcp").format(port),
            }

        return {
            "status": "error",
            "message": _("Unsupported OS for automated firewall fix."),
        }

    @staticmethod
    def fix_port(action: str, new_port: int = None) -> dict:
        if action == "change_port":
            if not new_port:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("", 0))
                new_port = s.getsockname()[1]
                s.close()
            config_manager.set("server_port", new_port)
            return {
                "status": "ok",
                "message": _("Port changed to {}. Restart PCLink.").format(new_port),
            }
        elif action == "kill_process":
            port = config_manager.get("server_port", 38080)
            try:
                if sys.platform == "win32":
                    res = subprocess.run(
                        f"netstat -ano | findstr :{port}",
                        shell=True,
                        capture_output=True,
                        text=True,
                    )
                    lines = res.stdout.strip().split("\n")
                    if lines and lines[0]:
                        pid = lines[0].strip().split()[-1]
                        subprocess.run(f"taskkill /PID {pid} /F", shell=True)
                        return {
                            "status": "ok",
                            "message": _("Killed process {} on port {}.").format(
                                pid, port
                            ),
                        }
                elif sys.platform.startswith("linux") or sys.platform == "darwin":
                    res = subprocess.run(
                        ["lsof", "-t", f"-i:{port}"], capture_output=True, text=True
                    )
                    pid = res.stdout.strip()
                    if pid:
                        subprocess.run(["kill", "-9", pid])
                        return {
                            "status": "ok",
                            "message": _("Killed process {} on port {}.").format(
                                pid, port
                            ),
                        }
                return {
                    "status": "error",
                    "message": _("Could not find process blocking the port."),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": _("Failed to kill process: {}").format(e),
                }
        return {"status": "error", "message": _("Invalid action.")}


repair_service = RepairService()

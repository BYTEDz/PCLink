# src/pclink/services/repair_service.py
import json
import logging
import shutil
import sqlite3
import subprocess
import sys

from ..core import constants
from ..core.config import config_manager
from ..core.device_manager import device_manager

log = logging.getLogger(__name__)


class RepairService:
    @staticmethod
    def check_port_availability(port: int) -> dict:
        import socket
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            s.close()
            return {"status": "ok", "message": f"Port {port} is available."}
        except OSError as e:
            # Check if it's our own PCLink instance holding it
            try:
                res = requests.get(
                    f"https://127.0.0.1:{port}/auth", verify=False, timeout=1
                )
                if "PCLink" in res.text or res.status_code == 200:
                    return {
                        "status": "ok",
                        "message": f"Port {port} is correctly bound by PCLink.",
                    }
            except Exception:
                try:
                    res2 = requests.get(f"http://127.0.0.1:{port}/auth", timeout=1)
                    if "PCLink" in res2.text or res2.status_code == 200:
                        return {
                            "status": "ok",
                            "message": f"Port {port} is correctly bound by PCLink.",
                        }
                except Exception:
                    pass

            return {
                "status": "warning",
                "message": f"Port {port} is in use by another application.",
                "error": str(e),
            }

    @staticmethod
    def check_db_integrity() -> dict:
        if not device_manager.db_path.exists():
            return {"status": "error", "message": "Database file is missing."}
        try:
            conn = sqlite3.connect(f"file:{device_manager.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == "ok":
                return {"status": "ok", "message": "Database is healthy."}
            else:
                return {"status": "error", "message": "Database corruption detected."}
        except sqlite3.DatabaseError as e:
            return {"status": "error", "message": f"Database error: {e}"}
        except Exception as e:
            return {"status": "error", "message": f"Unexpected error: {e}"}

    @staticmethod
    def check_config() -> dict:
        if not constants.CONFIG_FILE.exists():
            return {"status": "error", "message": "Config file is missing."}
        try:
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                json.load(f)
            return {"status": "ok", "message": "Config file is valid."}
        except json.JSONDecodeError as e:
            return {"status": "error", "message": f"Config JSON is invalid: {e}"}
        except Exception as e:
            return {"status": "error", "message": f"Config error: {e}"}

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
                        "message": "Windows Firewall rule is missing.",
                    }
                return {"status": "ok", "message": "Windows Firewall rule exists."}
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to check Windows firewall: {e}",
                }
        elif sys.platform.startswith("linux"):
            try:
                result = subprocess.run(
                    ["sudo", "-n", "ufw", "status"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    return {
                        "status": "warning",
                        "message": "UFW is active, ensure port 38080 is allowed.",
                    }
                return {
                    "status": "ok",
                    "message": "Linux firewall check requires manual verification or UFW is inactive.",
                }
            except Exception:
                return {
                    "status": "ok",
                    "message": "Linux firewall check requires manual verification.",
                }
        return {"status": "ok", "message": "Firewall check not supported on this OS."}

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
            return {"status": "error", "message": "No DB to fix."}
        try:
            backup_path = device_manager.db_path.with_suffix(".db.bak")
            shutil.copy2(device_manager.db_path, backup_path)
            device_manager.db_path.unlink()
            device_manager._init_db()
            return {
                "status": "ok",
                "message": f"Database recreated. Backup saved to {backup_path}",
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to fix DB: {e}"}

    @staticmethod
    def fix_config() -> dict:
        try:
            backup_path = constants.CONFIG_FILE.with_suffix(".json.bak")
            if constants.CONFIG_FILE.exists():
                shutil.copy2(constants.CONFIG_FILE, backup_path)
                constants.CONFIG_FILE.unlink()
            config_manager.load_config()
            config_manager.save_config()
            return {"status": "ok", "message": "Config reset to defaults."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to fix config: {e}"}

    @staticmethod
    def force_repair() -> dict:
        try:
            RepairService.fix_db()
            RepairService.fix_config()
            # Also clear transfers cache
            if constants.UPLOADS_PATH.exists():
                shutil.rmtree(constants.UPLOADS_PATH, ignore_errors=True)
                constants.UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
            if constants.DOWNLOADS_PATH.exists():
                shutil.rmtree(constants.DOWNLOADS_PATH, ignore_errors=True)
                constants.DOWNLOADS_PATH.mkdir(parents=True, exist_ok=True)

            return {
                "status": "ok",
                "message": "Factory reset complete. System is fresh.",
            }
        except Exception as e:
            return {"status": "error", "message": f"Force repair failed: {e}"}

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
                return {"status": "ok", "message": "Windows Firewall rule added."}
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to add firewall rule: {e}",
                }
        elif sys.platform.startswith("linux"):
            port = config_manager.get("server_port", 38080)
            # Try passwordless sudo first (if setup in sudoers)
            try:
                res = subprocess.run(
                    ["sudo", "-n", "ufw", "allow", f"{port}/tcp"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return {
                        "status": "ok",
                        "message": f"UFW rule added for port {port}.",
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
                            "message": f"UFW rule added for port {port}.",
                        }
                    return {
                        "status": "error",
                        "message": f"UFW command failed: {result.stderr}",
                    }
                except Exception as e:
                    return {"status": "error", "message": str(e)}

            # Try pkexec
            try:
                result = subprocess.run(
                    ["pkexec", "ufw", "allow", f"{port}/tcp"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return {
                        "status": "ok",
                        "message": f"UFW rule added for port {port} via GUI prompt.",
                    }
            except FileNotFoundError:
                pass

            return {
                "status": "warning",
                "message": f"Run manually: sudo ufw allow {port}/tcp",
            }

        return {
            "status": "error",
            "message": "Unsupported OS for automated firewall fix.",
        }

    @staticmethod
    def fix_port(action: str, new_port: int = None) -> dict:
        if action == "change_port":
            if not new_port:
                import socket

                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("", 0))
                new_port = s.getsockname()[1]
                s.close()
            config_manager.set("server_port", new_port)
            return {
                "status": "ok",
                "message": f"Port changed to {new_port}. Restart PCLink.",
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
                    lines = res.stdout.strip().split("\\n")
                    if lines and lines[0]:
                        pid = lines[0].strip().split()[-1]
                        subprocess.run(f"taskkill /PID {pid} /F", shell=True)
                        return {
                            "status": "ok",
                            "message": f"Killed process {pid} on port {port}.",
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
                            "message": f"Killed process {pid} on port {port}.",
                        }
                return {
                    "status": "error",
                    "message": "Could not find process blocking the port.",
                }
            except Exception as e:
                return {"status": "error", "message": f"Failed to kill process: {e}"}
        return {"status": "error", "message": "Invalid action."}


repair_service = RepairService()

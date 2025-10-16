#!/usr/bin/env python3
"""
PCLink Unified Build System

A robust, cross-platform build script for PyInstaller that can generate
portable archives, single-file executables, and native installers with a
consistent, professional naming convention.
"""
import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
# psutil imported conditionally when needed
from pathlib import Path

# Make the `src` directory available to find the real version_info module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

try:
    from pclink.core.version import version_info
except ImportError:
    print("[WARNING] Could not import real version_info. Using fallback dummy version.")
    try:
        import tomli
        with open("pyproject.toml", "rb") as f:
            pyproject = tomli.load(f)
            version_str = pyproject.get("project", {}).get("version", "0.0.0-dev")
    except (FileNotFoundError, ImportError):
        version_str = "0.0.0-dev"

    class DummyVersionInfo:
        def __init__(self, ver):
            self.version = ver
        @property
        def simple_version(self):
            return self.version.split("-")[0]
        def get_windows_version_info(self):
            ver_parts = self.simple_version.split('.') + ['0'] * (4 - len(self.simple_version.split('.')))
            file_version = ".".join(ver_parts[:4])
            return {
                "file_version": file_version,
                "product_version": file_version,
                "company_name": "BYTEDz",
                "file_description": "Remote PC Control Server",
                "product_name": "PCLink",
                "copyright": "Copyright © 2025 Azhar Zouhir / BYTEDz",
            }
    version_info = DummyVersionInfo(version_str)

APP_NAME = "PCLink"
MAIN_SCRIPT = "src/pclink/launcher.py"
# Define source directories relative to the project root
ASSETS_SOURCE_DIR = "src/pclink/assets"
WEBUI_SOURCE_DIR = "src/pclink/web_ui/static"
INNO_SETUP_TEMPLATE = "scripts/installer.iss"

HIDDEN_IMPORTS = [
    # Uvicorn and FastAPI core
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "fastapi.routing",
    "starlette.middleware.cors", "pydantic.v1", "anyio._backends._asyncio",
    
    # WebSocket support
    "websockets", "websockets.server", "websockets.client", "websockets.protocol",
    "websockets.extensions", "websockets.extensions.permessage_deflate",
    "wsproto", "wsproto.connection", "wsproto.events", "wsproto.extensions",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.protocols.websockets.wsproto_impl",
    
    # PCLink modules
    "pclink", "pclink.main", "pclink.launcher", "pclink.core", "pclink.api_server",
    "pclink.web_ui", "pclink.headless", "pclink.core.controller", "pclink.core.state",
    "pclink.core.config", "pclink.core.constants", "pclink.core.logging",
    "pclink.core.singleton", "pclink.core.utils", "pclink.core.version",
    "pclink.core.setup_guide", "pclink.core.web_auth", "pclink.core.device_manager",
    "pclink.core.validators",
    
    # API Server modules
    "pclink.api_server.api", "pclink.api_server.discovery", "pclink.api_server.file_browser",
    "pclink.api_server.process_manager", "pclink.api_server.terminal",
    
    # System integration
    "pystray", "getmac", "psutil", "cryptography.hazmat.backends", 
    "keyboard", "mss", "pyperclip",
    
    # Windows-specific (conditional)
    "win32api", "win32con", "win32gui", "win32process", "win32security", 
    "win32event", "win32file", "win32com.client", "pythoncom", "pycaw",
    

    
    # Networking and security
    "ssl", "socket", "http.server", "urllib.parse", "json", "base64"
]

class BuildError(Exception):
    pass


def check_system_dependencies(build_format=None):
    """Check for required system dependencies and tools."""
    missing_deps = []
    
    # Check Python version
    if sys.version_info < (3, 8):
        missing_deps.append(f"Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")
    
    # For FPM builds, only check FPM-specific dependencies
    if build_format == "fpm":
        # Check for FPM-specific tools only
        fpm_tools = ["ruby", "gem"]
        for tool in fpm_tools:
            if not shutil.which(tool):
                missing_deps.append(f"{tool} (required for FPM)")
        
        # Check for pip (needed to create wheel)
        if not shutil.which("pip") and not shutil.which("pip3"):
            missing_deps.append("pip (required to create Python wheel)")
        
        # Check for FPM
        try:
            subprocess.run(["fpm", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing_deps.append("fpm (Effing Package Management)")
        
        if missing_deps:
            print("[ERROR] Missing FPM dependencies:")
            for dep in missing_deps:
                print(f"  - {dep}")
            print("\nInstall FPM dependencies with:")
            print("  sudo apt install ruby ruby-dev rubygems build-essential dpkg-dev")
            print("  sudo gem install --no-document fpm")
            return False
        
        print("[INFO] FPM dependencies OK - ready to build packages")
        return True
    
    # For other build formats, check PyInstaller dependencies
    required_packages = [
        "PyInstaller", "psutil", "fastapi", "uvicorn", "cryptography", 
        "requests"
    ]
    
    # Optional packages that might not be available in headless environments
    optional_packages = ["mss", "keyboard", "pyautogui", "pystray"]
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_deps.append(f"Python package: {package}")
    
    # Check optional packages but only warn
    missing_optional = []
    for package in optional_packages:
        try:
            __import__(package)
        except ImportError:
            missing_optional.append(package)
    
    if missing_optional:
        print(f"[WARNING] Optional packages missing (may cause runtime issues): {', '.join(missing_optional)}")
    
    # Platform-specific checks
    if platform.system().lower() == "windows":
        try:
            import win32api
        except ImportError:
            missing_deps.append("Python package: pywin32 (Windows-specific)")
    
    # Check for build tools
    if not shutil.which("python"):
        missing_deps.append("python executable not found in PATH")
    
    # Check if running in CI environment
    is_ci = os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")
    if is_ci:
        print("[INFO] Running in CI environment - some checks may be relaxed")
    
    if missing_deps:
        print("[ERROR] Missing dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nInstall missing dependencies with:")
        print("  pip install -r requirements-dev.txt")
        return False
    
    return True


def verify_project_structure():
    """Verify that all required project files exist."""
    required_files = [
        "src/pclink/__init__.py",
        "src/pclink/main.py", 
        "src/pclink/launcher.py",
        "pyproject.toml"
    ]
    
    optional_files = [
        "src/pclink/assets",
        "src/pclink/web_ui/static"
    ]
    
    missing_files = []
    root_dir = Path.cwd()
    
    for file_path in required_files:
        full_path = root_dir / file_path
        if not full_path.exists():
            missing_files.append(file_path)
    
    if missing_files:
        print("[ERROR] Missing required project files:")
        for file_path in missing_files:
            print(f"  - {file_path}")
        return False
    
    # Check optional files and warn if missing
    for file_path in optional_files:
        full_path = root_dir / file_path
        if not full_path.exists():
            print(f"[WARNING] Optional file/directory missing: {file_path}")
    
    return True


class UninstallManager:
    """Handles PCLink uninstallation with process management and data cleanup."""
    
    def __init__(self):
        # Import psutil only when uninstall functionality is needed
        try:
            import psutil
            self.psutil = psutil
        except ImportError:
            raise ImportError("psutil is required for uninstall functionality. Install with: pip install psutil")
        
        self.app_name = "PCLink"
        self.process_names = ["pclink.exe", "PCLink.exe", "PCLink-build.exe"]
        self.registry_paths = [
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
            r"HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Run"
        ]
        
    def find_pclink_processes(self):
        """Find all running PCLink processes."""
        pclink_processes = []
        try:
            for proc in self.psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    proc_info = proc.info
                    proc_name = (proc_info.get('name') or '').lower()
                    proc_exe = (proc_info.get('exe') or '').lower()
                    proc_cmdline = ' '.join(proc_info.get('cmdline') or []).lower()
                    
                    # Check if this is a PCLink process
                    if (any(name.lower() in proc_name for name in self.process_names) or
                        'pclink' in proc_exe or 'pclink' in proc_cmdline):
                        pclink_processes.append({
                            'pid': proc_info['pid'],
                            'name': proc_info.get('name', 'Unknown'),
                            'exe': proc_info.get('exe', 'Unknown'),
                            'cmdline': proc_cmdline
                        })
                except (self.psutil.NoSuchProcess, self.psutil.AccessDenied, self.psutil.ZombieProcess):
                    continue
        except Exception as e:
            print(f"[WARNING] Error finding PCLink processes: {e}")
        
        return pclink_processes
    
    def terminate_pclink_processes(self, force=False):
        """Terminate all PCLink processes."""
        processes = self.find_pclink_processes()
        if not processes:
            print("[INFO] No PCLink processes found running.")
            return True
        
        print(f"[INFO] Found {len(processes)} PCLink process(es) running:")
        for proc in processes:
            print(f"  - PID {proc['pid']}: {proc['name']} ({proc['exe']})")
        
        if not force:
            response = input("\nTerminate these processes? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print("[INFO] Uninstall cancelled by user.")
                return False
        
        terminated = []
        failed = []
        
        for proc_info in processes:
            try:
                proc = self.psutil.Process(proc_info['pid'])
                proc.terminate()
                
                # Wait for graceful termination
                try:
                    proc.wait(timeout=5)
                    terminated.append(proc_info)
                    print(f"[OK] Terminated process {proc_info['pid']} ({proc_info['name']})")
                except self.psutil.TimeoutExpired:
                    # Force kill if graceful termination fails
                    proc.kill()
                    proc.wait(timeout=2)
                    terminated.append(proc_info)
                    print(f"[OK] Force-killed process {proc_info['pid']} ({proc_info['name']})")
                    
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied) as e:
                failed.append((proc_info, str(e)))
                print(f"[WARNING] Could not terminate process {proc_info['pid']}: {e}")
        
        if failed:
            print(f"[WARNING] Failed to terminate {len(failed)} process(es). Uninstall may be incomplete.")
            return len(terminated) > 0
        
        print(f"[OK] Successfully terminated {len(terminated)} PCLink process(es).")
        return True
    
    def find_installation_paths(self):
        """Find potential PCLink installation paths."""
        possible_paths = []
        
        # Common installation directories
        common_dirs = [
            Path.home() / "AppData" / "Local" / "Programs" / "PCLink",
            Path.home() / "AppData" / "Local" / "PCLink",
            Path("C:/Program Files/PCLink"),
            Path("C:/Program Files (x86)/PCLink"),
            Path.cwd(),  # Current directory (for portable installs)
        ]
        
        for path in common_dirs:
            if path.exists() and any(path.glob("*pclink*")):
                possible_paths.append(path)
        
        # Check registry for installation path (Windows)
        if platform.system().lower() == "windows":
            try:
                import winreg
                reg_paths = [
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PCLink"),
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PCLink"),
                ]
                
                for hkey, subkey in reg_paths:
                    try:
                        with winreg.OpenKey(hkey, subkey) as key:
                            install_location = winreg.QueryValueEx(key, "InstallLocation")[0]
                            if install_location and Path(install_location).exists():
                                possible_paths.append(Path(install_location))
                    except (FileNotFoundError, OSError):
                        continue
            except ImportError:
                pass
        
        return list(set(possible_paths))  # Remove duplicates
    
    def find_data_paths(self):
        """Find PCLink data and configuration directories."""
        data_paths = []
        
        # Common data directories
        if platform.system().lower() == "windows":
            app_data = Path.home() / "AppData" / "Roaming" / "PCLink"
            local_app_data = Path.home() / "AppData" / "Local" / "PCLink"
        else:
            app_data = Path.home() / ".config" / "pclink"
            local_app_data = Path.home() / ".local" / "share" / "pclink"
        
        for path in [app_data, local_app_data]:
            if path.exists():
                data_paths.append(path)
        
        return data_paths
    
    def remove_startup_entries(self):
        """Remove PCLink from startup (Windows registry and startup folder)."""
        removed_entries = []
        
        if platform.system().lower() != "windows":
            return removed_entries
        
        try:
            import winreg
            
            # Remove from registry startup entries
            for reg_path in self.registry_paths:
                try:
                    if "HKEY_CURRENT_USER" in reg_path:
                        hkey = winreg.HKEY_CURRENT_USER
                        subkey = reg_path.split("\\", 1)[1]
                    else:
                        hkey = winreg.HKEY_LOCAL_MACHINE
                        subkey = reg_path.split("\\", 1)[1]
                    
                    with winreg.OpenKey(hkey, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
                        try:
                            winreg.DeleteValue(key, "PCLink")
                            removed_entries.append(f"Registry: {reg_path}\\PCLink")
                        except FileNotFoundError:
                            pass  # Entry doesn't exist
                except (OSError, PermissionError) as e:
                    print(f"[WARNING] Could not access registry path {reg_path}: {e}")
            
            # Remove from startup folder
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            for startup_file in startup_folder.glob("*PCLink*"):
                try:
                    startup_file.unlink()
                    removed_entries.append(f"Startup folder: {startup_file}")
                except Exception as e:
                    print(f"[WARNING] Could not remove startup file {startup_file}: {e}")
        
        except ImportError:
            print("[WARNING] Could not import winreg module for startup cleanup")
        
        return removed_entries
    
    def remove_firewall_rules(self):
        """Remove PCLink firewall rules (Windows)."""
        removed_rules = []
        
        if platform.system().lower() != "windows":
            return removed_rules
        
        try:
            # List of possible rule names
            rule_names = ["PCLink Server", "PCLink", "PCLink Remote Control Server"]
            
            for rule_name in rule_names:
                try:
                    cmd = ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={rule_name}']
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0 and "Ok" in result.stdout:
                        removed_rules.append(rule_name)
                        print(f"[OK] Removed firewall rule: {rule_name}")
                    elif "No rules match" not in result.stderr:
                        print(f"[WARNING] Could not remove firewall rule {rule_name}: {result.stderr}")
                
                except Exception as e:
                    print(f"[WARNING] Error removing firewall rule {rule_name}: {e}")
        
        except Exception as e:
            print(f"[WARNING] Error during firewall cleanup: {e}")
        
        return removed_rules
    
    def uninstall(self, keep_data=False, remove_ports=False, force=False):
        """Perform complete PCLink uninstall."""
        print(f"\n--- PCLink Uninstaller ---")
        print(f"Keep user data: {keep_data}")
        print(f"Remove firewall rules: {remove_ports}")
        print(f"Force mode: {force}")
        print("-" * 30)
        
        # Step 1: Terminate running processes
        print("\n[STEP 1] Checking for running PCLink processes...")
        if not self.terminate_pclink_processes(force=force):
            return False
        
        # Step 2: Find and remove installation files
        print("\n[STEP 2] Finding installation files...")
        install_paths = self.find_installation_paths()
        
        if install_paths:
            print(f"Found {len(install_paths)} installation path(s):")
            for path in install_paths:
                print(f"  - {path}")
            
            if not force:
                response = input("\nRemove these installation directories? (y/N): ").strip().lower()
                if response not in ['y', 'yes']:
                    print("[INFO] Skipping installation file removal.")
                else:
                    for path in install_paths:
                        try:
                            if path.is_file():
                                path.unlink()
                            else:
                                shutil.rmtree(path)
                            print(f"[OK] Removed: {path}")
                        except Exception as e:
                            print(f"[ERROR] Could not remove {path}: {e}")
            else:
                for path in install_paths:
                    try:
                        if path.is_file():
                            path.unlink()
                        else:
                            shutil.rmtree(path)
                        print(f"[OK] Removed: {path}")
                    except Exception as e:
                        print(f"[ERROR] Could not remove {path}: {e}")
        else:
            print("[INFO] No installation directories found.")
        
        # Step 3: Handle user data
        print("\n[STEP 3] Checking user data...")
        data_paths = self.find_data_paths()
        
        if data_paths:
            print(f"Found {len(data_paths)} data directory(ies):")
            for path in data_paths:
                print(f"  - {path}")
            
            if not keep_data:
                if not force:
                    response = input("\nRemove user data directories? (y/N): ").strip().lower()
                    if response not in ['y', 'yes']:
                        print("[INFO] Keeping user data directories.")
                    else:
                        for path in data_paths:
                            try:
                                shutil.rmtree(path)
                                print(f"[OK] Removed data: {path}")
                            except Exception as e:
                                print(f"[ERROR] Could not remove data {path}: {e}")
                else:
                    for path in data_paths:
                        try:
                            shutil.rmtree(path)
                            print(f"[OK] Removed data: {path}")
                        except Exception as e:
                            print(f"[ERROR] Could not remove data {path}: {e}")
            else:
                print("[INFO] Keeping user data as requested.")
        else:
            print("[INFO] No user data directories found.")
        
        # Step 4: Remove startup entries
        print("\n[STEP 4] Removing startup entries...")
        startup_entries = self.remove_startup_entries()
        if startup_entries:
            for entry in startup_entries:
                print(f"[OK] Removed startup entry: {entry}")
        else:
            print("[INFO] No startup entries found.")
        
        # Step 5: Remove firewall rules
        if remove_ports:
            print("\n[STEP 5] Removing firewall rules...")
            firewall_rules = self.remove_firewall_rules()
            if firewall_rules:
                for rule in firewall_rules:
                    print(f"[OK] Removed firewall rule: {rule}")
            else:
                print("[INFO] No firewall rules found.")
        else:
            print("\n[STEP 5] Skipping firewall rule removal.")
        
        print("\n[DONE] PCLink uninstall completed.")
        return True

class Builder:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.root_dir = Path.cwd()
        self.dist_dir = self.root_dir / "dist"
        self.build_dir = self.root_dir / "build"
        self.releases_dir = self.root_dir / "releases"
        self.assets_dir = self.root_dir / ASSETS_SOURCE_DIR
        self.platform = platform.system().lower()
        self.version = version_info.version
        self.arch = "x86_64" if platform.machine().lower() in ["amd64", "x86_64"] else platform.machine()

    def _get_pyinstaller_icon(self) -> Path | None:
        icon_path = self.assets_dir / "icon.png"
        return icon_path if icon_path.exists() else None
        
    def _get_inno_setup_icon(self) -> Path | None:
        if self.platform != "windows": return None
        return self._ensure_icon()

    def _run_command(self, cmd: list, check: bool = True):
        print(f"[RUN] {' '.join(str(c) for c in cmd)}")
        try:
            result = subprocess.run(cmd, check=check, text=True, encoding='utf-8', capture_output=not self.debug)
            if not self.debug and result.returncode != 0:
                print(f"[WARNING] Command returned non-zero exit code: {result.returncode}")
                if result.stdout:
                    print(f"STDOUT: {result.stdout}")
                if result.stderr:
                    print(f"STDERR: {result.stderr}")
            return result
        except FileNotFoundError as e:
            raise BuildError(f"Command not found: {e.filename}. Make sure it's installed and in PATH.")
        except subprocess.CalledProcessError as e:
            error_msg = f"Command failed with exit code {e.returncode}"
            if e.stdout:
                error_msg += f"\nSTDOUT:\n{e.stdout}"
            if e.stderr:
                error_msg += f"\nSTDERR:\n{e.stderr}"
            raise BuildError(error_msg)

    def clean(self):
        print("[CLEAN] Removing previous build artifacts...")
        for d in [self.dist_dir, self.build_dir]:
            if d.exists(): shutil.rmtree(d)
        for spec_file in self.root_dir.glob("*.spec"):
            spec_file.unlink()

    def _ensure_icon(self):
        """Returns the existing icon.ico file if present."""
        icon_path = self.assets_dir / "icon.ico"
        if not icon_path.exists():
            print("[WARNING] icon.ico not found. InnoSetup may require it.")
        return icon_path if icon_path.exists() else None

    def build(self, onefile: bool, name: str):
        print(f"[BUILD] Starting PyInstaller build (mode: {'one-file' if onefile else 'one-dir'})...")
        
        # Verify PyInstaller is available
        if not shutil.which("pyinstaller") and not shutil.which(f"{sys.executable} -m PyInstaller"):
            raise BuildError("PyInstaller not found. Install with: pip install pyinstaller")
        
        icon_path = self._get_pyinstaller_icon()
        
        # Define web UI static files source directory
        web_ui_static_dir = self.root_dir / WEBUI_SOURCE_DIR
        
        # Verify required directories exist
        if not self.assets_dir.exists():
            print(f"[WARNING] Assets directory not found: {self.assets_dir}")
        
        if not web_ui_static_dir.exists():
            print(f"[WARNING] Web UI static directory not found: {web_ui_static_dir}")
        
        cmd = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", f"--name={name}",
            f"--distpath={self.dist_dir}", f"--workpath={self.build_dir}",
            f"--specpath={self.build_dir}",
            "--paths=src",
        ]
        
        # Add data directories only if they exist
        if self.assets_dir.exists():
            cmd.append(f"--add-data={self.assets_dir}{os.pathsep}src/pclink/assets")
        
        if web_ui_static_dir.exists():
            cmd.append(f"--add-data={web_ui_static_dir}{os.pathsep}src/pclink/web_ui/static")
        
        cmd.append("--onefile" if onefile else "--onedir")
        if self.debug: 
            cmd.append("--console")
        else: 
            cmd.extend(["--windowed", "--disable-windowed-traceback"])
        
        if icon_path:
            cmd.append(f"--icon={icon_path}")
        
        for imp in HIDDEN_IMPORTS: 
            cmd.append(f"--hidden-import={imp}")
        
        # Verify main script exists
        main_script_path = self.root_dir / MAIN_SCRIPT
        if not main_script_path.exists():
            raise BuildError(f"Main script not found: {main_script_path}")
        
        cmd.append(MAIN_SCRIPT)
        self._run_command(cmd)
        print("[OK] PyInstaller build successful.")

    def package(self, build_name: str, package_name: str, onefile: bool):
        self.releases_dir.mkdir(exist_ok=True)
        if onefile:
            source_file = self.dist_dir / build_name
            ext = ".exe" if self.platform == "windows" else ""
            if self.platform == "windows" and not source_file.suffix: source_file = source_file.with_suffix(".exe")
            final_name = f"{package_name}{ext}"
            shutil.move(source_file, self.releases_dir / final_name)
            print(f"[OK] Packaged one-file executable: {final_name}")
        else:
            source_dir = self.dist_dir / build_name
            archive_format = "zip" if self.platform == "windows" else "gztar"
            archive_path = Path(shutil.make_archive(str(self.releases_dir / package_name), archive_format, self.dist_dir, build_name))
            print(f"[OK] Packaged portable archive: {archive_path.name}")

    def create_windows_installer(self, build_name: str, package_name: str):
        print("[INSTALLER] Creating Windows installer...")
        if self.platform != "windows": raise BuildError("Installers only on Windows.")
        
        iscc_path = self._find_inno_setup()
        if not iscc_path: raise BuildError("Inno Setup compiler (ISCC.exe) not found. Ensure it was installed by the workflow.")

        template_path = self.root_dir / INNO_SETUP_TEMPLATE
        if not template_path.exists(): raise BuildError(f"Template not found: {template_path}")

        source_dir = (self.dist_dir / build_name).resolve()
        content = template_path.read_text(encoding='utf-8')
        win_ver = version_info.get_windows_version_info()
        
        replacements = {
            "__APP_VERSION__": self.version,
            "__COMPANY_NAME__": win_ver["company_name"],
            "__FILE_VERSION__": win_ver["file_version"],
            "__PRODUCT_VERSION__": win_ver["product_version"],
            "__COPYRIGHT__": win_ver["copyright"],
            "__EXECUTABLE_NAME__": f"{build_name}.exe",
            "__SOURCE_DIR__": str(source_dir),
            "__OUTPUT_BASE_FILENAME__": package_name,
            "__SETUP_ICON_FILE__": str(self._get_inno_setup_icon() or ""),
            "__OUTPUT_DIR__": str(self.releases_dir.resolve()),
        }
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        
        license_path = self.root_dir / "LICENSE"
        if license_path.exists():
            content = content.replace("__LICENSE_FILE__", str(license_path.resolve()))
        else:
            content = content.replace("LicenseFile=__LICENSE_FILE__", "; LicenseFile not found")
        
        processed_iss_path = self.build_dir / "processed.iss"
        processed_iss_path.write_text(content, encoding='utf-8')

        print(f"[INFO] Generated Inno Setup script: {processed_iss_path}")
        self._run_command([str(iscc_path), str(processed_iss_path)])
        print(f"[OK] Created Windows installer: {self.releases_dir / package_name}.exe")

    def _find_inno_setup(self) -> Path | None:
        if path := shutil.which("ISCC.exe"): return Path(path)
        for path_str in [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")]:
            if path_str and (iscc := Path(path_str) / "Inno Setup 6" / "ISCC.exe").exists(): return iscc
        return None



def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Unified Build System")
    parser.add_argument("--format", default="portable", choices=["portable", "installer", "onefile", "fpm"], help="Output format.")
    parser.add_argument("--clean", action="store_true", help="Clean build directories before starting.")
    parser.add_argument("--debug", action="store_true", help="Create a debug build with console.")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall PCLink from the system.")
    parser.add_argument("--keep-data", action="store_true", help="Keep user data during uninstall.")
    parser.add_argument("--remove-ports", action="store_true", help="Remove firewall rules during uninstall.")
    parser.add_argument("--force", action="store_true", help="Force operations without user confirmation.")
    args = parser.parse_args()
    
    # Handle uninstall mode
    if args.uninstall:
        try:
            uninstaller = UninstallManager()
            success = uninstaller.uninstall(
                keep_data=args.keep_data,
                remove_ports=args.remove_ports,
                force=args.force
            )
            sys.exit(0 if success else 1)
        except Exception as e:
            print(f"\n[FAIL] UNINSTALL FAILED: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        start_time = time.monotonic()
        
        print(f"--- {APP_NAME} Builder v{version_info.version} ---")
        print(f"[INFO] Performing pre-build checks...")
        
        # Run system checks
        if not check_system_dependencies(args.format):
            raise BuildError("System dependency check failed")
        
        if not verify_project_structure():
            raise BuildError("Project structure verification failed")
        
        builder = Builder(debug=args.debug)
        
        if args.clean: 
            builder.clean()
        builder.releases_dir.mkdir(exist_ok=True)

        os_name = "windows" if builder.platform == "windows" else builder.platform
        base_name = f"{APP_NAME}-{builder.version}-{os_name}-{builder.arch}"
        internal_build_name = "PCLink-build"

        print(f"[INFO] Building format: {args.format} for {os_name}-{builder.arch}")

        if args.format == "portable":
            builder.build(onefile=False, name=internal_build_name)
            builder.package(build_name=internal_build_name, package_name=f"{base_name}-portable", onefile=False)
        elif args.format == "onefile":
            builder.build(onefile=True, name=internal_build_name)
            builder.package(build_name=internal_build_name, package_name=base_name, onefile=True)
        elif args.format == "installer":
            installer_source_name = APP_NAME
            builder.build(onefile=False, name=installer_source_name)
            builder.create_windows_installer(build_name=installer_source_name, package_name=f"{base_name}-installer")
        elif args.format == "fpm":
            if builder.platform != "linux":
                raise BuildError("FPM packaging is only available on Linux.")
            sys.path.insert(0, str(Path(__file__).parent))
            from build_fpm import FPMBuilder
            fpm_builder = FPMBuilder()
            fpm_success = fpm_builder.build_all(["deb", "rpm"])
            if not fpm_success:
                raise BuildError("FPM package build failed.")


        print(f"\n[DONE] Operation completed in {time.monotonic() - start_time:.2f} seconds.")

    except (BuildError, KeyboardInterrupt) as e:
        print(f"\n[FAIL] BUILD FAILED: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
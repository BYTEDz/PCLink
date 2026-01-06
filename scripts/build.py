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
    "ssl", "socket", "http.server", "urllib.parse", "json", "base64",
    
    # Plugin metadata parsing
    "yaml"
]

class BuildError(Exception):
    pass


def check_system_dependencies(build_format=None):
    """Check for required system dependencies and tools."""
    missing_deps = []
    
    # Check Python version
    if sys.version_info < (3, 8):
        missing_deps.append(f"Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")
    
    # For NFPM builds, we only need to ensure the Python environment is ready 
    # to run the pre-build script and create a wheel.
    if build_format == "nfpm":
        # Check for pip (needed to create wheel)
        if not shutil.which("pip") and not shutil.which("pip3"):
            missing_deps.append("pip (required to create Python wheel for NFPM staging)")
        
        if missing_deps:
            print("[ERROR] Missing NFPM pre-build dependencies:")
            for dep in missing_deps:
                print(f"  - {dep}")
            return False
        
        print("[INFO] NFPM pre-build dependencies OK.")
        return True
    
    # For other build formats (PyInstaller), check core dependencies
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
        print("  pip install -e '.[dev]'")
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
    parser.add_argument("--format", default="portable", choices=["portable", "installer", "onefile", "nfpm", "wheel"], help="Output format.")
    parser.add_argument("--clean", action="store_true", help="Clean build directories before starting.")
    parser.add_argument("--debug", action="store_true", help="Create a debug build with console.")
    args = parser.parse_args()

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
            
        elif args.format == "nfpm":
            # NFPM can run cross-platform, but packages are for Linux
            print("[INFO] Building Linux packages using NFPM...")
            
            # Step 1: Ensure we have a fresh wheel from the same build process
            print("[INFO] Building Python wheel for NFPM...")
            wheel_builder = Builder(debug=args.debug)
            
            # Use 'build' module efficiently
            cmd = [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_builder.dist_dir)]
            # We want to use the same logic as the wheel command, so we just run the command directly here
            # to ensure we have the path to the precise wheel that was built.
            wheel_builder._run_command(cmd)
            
            wheel_files = list(wheel_builder.dist_dir.glob("*.whl"))
            if not wheel_files:
                raise BuildError("Wheel creation failed during NFPM prep")
            
            wheel_path = wheel_files[0]
            print(f"[INFO] Using wheel: {wheel_path}")

            # Step 2: Run NFPM Pre-packaging using the shared logic
            sys.path.insert(0, str(Path(__file__).parent))
            from build_nfpm import NFPMBuilder
            
            nfpm_builder = NFPMBuilder()
            # Pass the wheel path we just built
            nfpm_builder.install_application_files(existing_wheel_path=wheel_path)
            nfpm_builder.create_staging_structure()
            # Note: install_application_files calls create_staging_structure? 
            # Actually checking `build_nfpm.py`:
            # - build_all() calls clean(), create_staging_structure(), install_application_files(), create_scripts(), generate_nfpm_config()
            # We should call these manually to inject the wheel.
            
            nfpm_builder.clean()
            nfpm_builder.create_staging_structure()
            nfpm_builder.install_application_files(existing_wheel_path=wheel_path)
            nfpm_builder.create_scripts()
            nfpm_builder.generate_nfpm_config()
            
            print("\n[INFO] NFPM pre-build complete. Starting final packaging...")

            # Check for nfpm executable
            if not shutil.which("nfpm"):
                raise BuildError("`nfpm` command not found. Please install nfpm to build packages.")

            # Define formats and build packages
            package_formats = ["deb", "rpm"]
            for fmt in package_formats:
                print(f"--- Building {fmt.upper()} package ---")
                cmd = [
                    "nfpm", "package",
                    "--packager", fmt,
                    "--target", str(builder.releases_dir),
                    "-f", "nfpm.yaml"
                ]
                builder._run_command(cmd)
                print(f"[OK] Successfully created {fmt} package.")
        
        elif args.format == "wheel":
            print("[INFO] Building Python wheel distribution...")
            
            # Check for build module or setuptools
            has_build = False
            try:
                import build
                has_build = True
            except ImportError:
                print("[WARNING] 'build' module not found, trying setuptools fallback...")
            
            # Clean dist directory if requested
            if args.clean and builder.dist_dir.exists():
                shutil.rmtree(builder.dist_dir)
            
            builder.dist_dir.mkdir(exist_ok=True)
            
            if has_build:
                # Use python -m build (preferred method)
                cmd = [sys.executable, "-m", "build", "--wheel", "--outdir", str(builder.dist_dir)]
                builder._run_command(cmd)
            else:
                # Fallback to setup.py bdist_wheel
                print("[INFO] Using setuptools fallback to build wheel...")
                cmd = [sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(builder.dist_dir)]
                builder._run_command(cmd)
            
            # Move wheel to releases directory
            builder.releases_dir.mkdir(exist_ok=True)
            wheel_files = list(builder.dist_dir.glob("*.whl"))
            if not wheel_files:
                raise BuildError("No wheel file was created")
            
            for wheel_file in wheel_files:
                dest = builder.releases_dir / wheel_file.name
                shutil.move(wheel_file, dest)
                print(f"[OK] Created Python wheel: {dest.name}")


        print(f"\n[DONE] Operation completed in {time.monotonic() - start_time:.2f} seconds.")

    except (BuildError, KeyboardInterrupt) as e:
        print(f"\n[FAIL] BUILD FAILED: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
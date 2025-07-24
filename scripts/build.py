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
                "copyright": "Copyright © 2025 AZHAR ZOUHIR / BYTEDz",
            }
    version_info = DummyVersionInfo(version_str)

APP_NAME = "PCLink"
MAIN_SCRIPT = "src/pclink/launcher.py"
ASSETS_DIR = "src/pclink/assets"
INNO_SETUP_TEMPLATE = "scripts/installer.iss"
HIDDEN_IMPORTS = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "fastapi.routing",
    "starlette.middleware.cors", "pydantic.v1", "anyio._backends._asyncio",
    "PySide6.QtSvg", "PySide6.QtNetwork", "pclink.main", "pclink.launcher",
    "pclink.core", "pclink.api_server", "pclink.gui", "pynput", "win32api",
    "win32con", "win32gui", "win32process", "win32security", "win32event",
    "win32file", "win32com.client", "pythoncom", "psutil",
    "cryptography.hazmat.backends", "keyboard", "mss", "pyperclip", "qrcode.image.pil"
]

class BuildError(Exception):
    pass

class Builder:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.root_dir = Path.cwd()
        self.dist_dir = self.root_dir / "dist"
        self.build_dir = self.root_dir / "build"
        self.releases_dir = self.root_dir / "releases"
        self.assets_dir = self.root_dir / ASSETS_DIR
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
            return subprocess.run(cmd, check=check, text=True, encoding='utf-8', capture_output=not self.debug)
        except FileNotFoundError as e:
            raise BuildError(f"Command not found: {e.filename}")
        except subprocess.CalledProcessError as e:
            raise BuildError(f"Command failed with exit code {e.returncode}.\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")

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
        
        # Ensure we have a properly formatted icon
        icon_path = self._get_pyinstaller_icon()
        
        cmd = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", f"--name={name}",
            f"--distpath={self.dist_dir}", f"--workpath={self.build_dir}",
            f"--specpath={self.build_dir}", f"--add-data={self.assets_dir}{os.pathsep}{ASSETS_DIR}",
            "--paths=src",  # This is the critical fix
        ]
        cmd.append("--onefile" if onefile else "--onedir")
        if self.debug: cmd.append("--console")
        else: cmd.extend(["--windowed", "--disable-windowed-traceback"])
        
        if icon_path:
            cmd.append(f"--icon={icon_path}")
        for imp in HIDDEN_IMPORTS: cmd.append(f"--hidden-import={imp}")
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
    parser.add_argument("--format", default="portable", choices=["portable", "installer", "onefile"], help="Output format.")
    parser.add_argument("--clean", action="store_true", help="Clean build directories before starting.")
    parser.add_argument("--debug", action="store_true", help="Create a debug build with console.")
    args = parser.parse_args()

    try:
        start_time = time.monotonic()
        builder = Builder(debug=args.debug)
        
        if args.clean: builder.clean()
        builder.releases_dir.mkdir(exist_ok=True)

        os_name = "windows" if builder.platform == "windows" else builder.platform
        base_name = f"{APP_NAME}-{builder.version}-{os_name}-{builder.arch}"
        internal_build_name = "PCLink-build"

        print(f"--- {APP_NAME} Builder v{builder.version} ---")
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

        print(f"\n[DONE] Operation completed in {time.monotonic() - start_time:.2f} seconds.")

    except (BuildError, KeyboardInterrupt) as e:
        print(f"\n[FAIL] BUILD FAILED: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
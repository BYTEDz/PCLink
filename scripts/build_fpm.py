#!/usr/bin/env python3
"""
PCLink FPM Package Builder

Uses FPM (Effing Package Management) to create native packages for multiple
Linux distributions from a single build configuration.

Supports: DEB, RPM, TAR.XZ, PKG (FreeBSD), and more.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Add src to path for version info
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

try:
    from pclink.core.version import version_info
    VERSION = version_info.version
except ImportError:
    VERSION = "2.0.0"

def check_system_requirements():
    """Check for required system dependencies for FPM building."""
    missing_deps = []
    
    # Check if running in CI environment
    is_ci = os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")
    if is_ci:
        print("[INFO] Running in CI environment")
    
    # Check for FPM
    if not shutil.which("fpm"):
        missing_deps.append("fpm (Effing Package Management)")
    
    # Check for Ruby (required for FPM)
    if not shutil.which("ruby"):
        missing_deps.append("ruby")
    
    # Check for gem (Ruby package manager)
    if not shutil.which("gem"):
        missing_deps.append("gem (Ruby package manager)")
    
    # Check for Python and pip
    if not shutil.which("python3") and not shutil.which("python"):
        missing_deps.append("python3 or python")
    
    if not shutil.which("pip3") and not shutil.which("pip"):
        missing_deps.append("pip3 or pip")
    
    # Check for build tools
    build_tools = ["gcc", "make"]
    for tool in build_tools:
        if not shutil.which(tool):
            missing_deps.append(f"{tool} (build tools)")
    
    # Check for distribution-specific package tools
    distro_tools = {
        "dpkg": "dpkg-dev (for DEB packages)",
        "rpm": "rpm-build (for RPM packages)", 
        "rpmbuild": "rpm-build (for RPM packages)"
    }
    
    available_tools = []
    for tool, desc in distro_tools.items():
        if shutil.which(tool):
            available_tools.append(tool)
    
    if not available_tools:
        missing_deps.append("At least one of: dpkg-dev, rpm-build")
    
    if missing_deps:
        print("[ERROR] Missing system dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        
        if not is_ci:
            print("\nInstall missing dependencies:")
            print("  # Ubuntu/Debian:")
            print("  sudo apt update")
            print("  sudo apt install ruby ruby-dev rubygems build-essential dpkg-dev")
            print("  sudo gem install --no-document fpm")
            print("\n  # Fedora/RHEL:")
            print("  sudo dnf install ruby ruby-devel rubygems rpm-build gcc make")
            print("  sudo gem install --no-document fpm")
            print("\n  # Arch Linux:")
            print("  sudo pacman -S ruby rubygems base-devel")
            print("  sudo gem install --no-document fpm")
        else:
            print("\nFor GitHub Actions, ensure your workflow installs these dependencies")
        
        return False
    
    return True


def verify_python_environment():
    """Verify Python environment and required packages."""
    missing_packages = []
    
    # Check Python version
    if sys.version_info < (3, 8):
        print(f"[ERROR] Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")
        return False
    
    # Check for required Python packages
    required_packages = [
        "fastapi", "uvicorn", "psutil", "cryptography", "requests", 
        "qrcode", "PIL", "mss", "keyboard", "pyautogui", "pystray"
    ]
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("[ERROR] Missing Python packages:")
        for pkg in missing_packages:
            print(f"  - {pkg}")
        print("\nInstall with: pip install -r requirements.txt")
        return False
    
    return True


class FPMBuilder:
    def __init__(self):
        self.root_dir = Path.cwd()
        self.build_dir = self.root_dir / "build" / "fpm"
        self.releases_dir = self.root_dir / "releases"
        self.package_name = "pclink"
        self.staging_dir = self.build_dir / "staging"
        
        # Package metadata
        self.metadata = {
            "name": self.package_name,
            "version": VERSION,
            "description": "Remote PC Control and File Management",
            "long_description": (
                "PCLink enables secure remote control and management of PCs from mobile devices. "
                "Features include file browsing, process management, terminal access, media control, "
                "and clipboard synchronization over HTTPS with API key authentication."
            ),
            "maintainer": "Azhar Zouhir <support@bytedz.xyz>",
            "vendor": "BYTEDz",
            "license": "AGPL-3.0",
            "url": "https://github.com/BYTEDz/pclink",
            "category": "Network",
            "architecture": "amd64",
        }
        
        # Distribution-specific configurations
        self.distributions = {
            "deb": {
                "depends": [
                    "python3 (>= 3.8)",
                    "python3-pip",
                    "python3-venv",
                    "libxcb-cursor0",
                    "libxcb-xinerama0",
                    "libxcb-randr0",
                    "libxcb-render-util0",
                    "libxcb-keysyms1",
                    "libxcb-image0",
                    "libxcb-icccm4",
                    "python3-gi",
                    "gir1.2-appindicator3-0.1",
                    "gir1.2-gtk-3.0",

                    "systemd | sysvinit-core | runit",
                    "dbus",
                ],
                "conflicts": [],
                "provides": [],
                "replaces": [],
            },
            "rpm": {
                "depends": [
                    "python3 >= 3.8",
                    "python3-pip",
                    "python3-virtualenv",
                    "libxcb",
                    "xcb-util-cursor",
                    "xcb-util-keysyms",
                    "xcb-util-image",
                    "xcb-util-wm",
                    "python3-gobject",
                    "libappindicator-gtk3",
                ],
                "conflicts": [],
                "provides": [],
                "replaces": [],
            },
            "pacman": {
                "depends": [
                    "python>=3.8",
                    "python-pip",
                    "python-virtualenv",
                    "libxcb",
                    "xcb-util-cursor",
                    "xcb-util-keysyms",
                    "xcb-util-image",
                    "xcb-util-wm",
                    "python-gobject",
                    "libappindicator-gtk3",
                ],
                "conflicts": [],
                "provides": [],
                "replaces": [],
            },
            "freebsd": {
                "depends": [
                    "python38",
                    "py38-pip",
                    "py38-virtualenv",
                    "libxcb",
                    "xcb-util-cursor",
                    "xcb-util-keysyms",
                    "xcb-util-image",
                    "xcb-util-wm",
                ],
                "conflicts": [],
                "provides": [],
                "replaces": [],
            }
        }
        
    def verify_build_environment(self):
        """Verify the build environment is ready."""
        print("[CHECK] Verifying build environment...")
        
        if not check_system_requirements():
            return False
        
        if not verify_python_environment():
            return False
        
        required_files = [
            "src/pclink/__init__.py",
            "src/pclink/main.py",
            "pyproject.toml",
            "requirements.txt"
        ]
        
        missing_files = []
        for file_path in required_files:
            if not (self.root_dir / file_path).exists():
                missing_files.append(file_path)
        
        if missing_files:
            print("[ERROR] Missing required project files:")
            for file_path in missing_files:
                print(f"  - {file_path}")
            return False
        
        try:
            result = subprocess.run(["fpm", "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                print(f"[ERROR] FPM test failed: {result.stderr}")
                return False
            print(f"[OK] FPM version: {result.stdout.strip()}")
        except Exception as e:
            print(f"[ERROR] FPM test failed: {e}")
            return False
        
        return True
        
    def clean(self):
        """Clean previous build artifacts."""
        print("[CLEAN] Removing previous FPM build artifacts...")
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
            
    def create_staging_structure(self):
        """Create the staging directory structure."""
        print("[STRUCTURE] Creating package staging structure...")
        
        dirs = [
            self.staging_dir / "usr" / "lib" / "pclink",
            self.staging_dir / "usr" / "bin",
            self.staging_dir / "usr" / "share" / "applications",
            self.staging_dir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps",
            self.staging_dir / "usr" / "share" / "doc" / "pclink",
            self.staging_dir / "usr" / "share" / "man" / "man1",

            self.staging_dir / "usr" / "lib" / "systemd" / "user",

            self.staging_dir / "etc" / "sudoers.d",
        ]
        
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
            
    def create_wheel(self):
        """Create a wheel of the current package."""
        print("[WHEEL] Creating Python wheel...")
        
        wheel_dir = self.build_dir / "wheels"
        wheel_dir.mkdir(parents=True, exist_ok=True)
        
        for old_wheel in wheel_dir.glob("*.whl"):
            old_wheel.unlink()
        
        cmd = [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), "."]
        try:
            result = subprocess.run(cmd, check=True, cwd=self.root_dir, capture_output=True, text=True)
            print(f"[OK] Wheel build completed")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Wheel build failed:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise RuntimeError("Wheel creation failed")
        
        wheel_files = list(wheel_dir.glob("*.whl"))
        if not wheel_files:
            print(f"[ERROR] No wheel files found in {wheel_dir}")
            print(f"Directory contents: {list(wheel_dir.iterdir())}")
            raise RuntimeError("No wheel file was created")
        
        wheel_path = wheel_files[0]
        print(f"[OK] Created wheel: {wheel_path.name}")
        return wheel_path
        
    def install_application_files(self):
        """Install the application files to staging directory."""
        print("[FILES] Installing application files...")
        
        wheel_path = self.create_wheel()
        wheel_dest = self.staging_dir / "usr" / "lib" / "pclink" / wheel_path.name
        shutil.copy2(wheel_path, wheel_dest)
        
        launcher_content = f"""#!/bin/bash
# PCLink Launcher Script
INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="/tmp/pclink-launcher.log"

# Log function
log() {{
    echo "$(date): $1" >> "$LOG_FILE"
}}

log "PCLink launcher started with args: $@"

if [ ! -d "$VENV_DIR" ]; then
    log "ERROR: Virtual environment not found at $VENV_DIR"
    echo "Error: PCLink virtual environment not found. Try reinstalling the package."
    exit 1
fi

if [ ! -f "$VENV_DIR/bin/pclink" ]; then
    log "ERROR: PCLink executable not found at $VENV_DIR/bin/pclink"
    log "Contents of $VENV_DIR/bin/: $(ls -la $VENV_DIR/bin/ 2>/dev/null || echo 'directory not accessible')"
    echo "Error: PCLink not properly installed. Try reinstalling the package."
    exit 1
fi

log "Starting PCLink from $VENV_DIR/bin/pclink"

"$VENV_DIR/bin/pclink" "$@" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${{PIPESTATUS[0]}}

log "PCLink exited with code: $EXIT_CODE"
exit $EXIT_CODE
"""
        
        launcher_path = self.staging_dir / "usr" / "bin" / "pclink"
        launcher_path.write_text(launcher_content)
        launcher_path.chmod(0o755)
        
        # Install power wrapper script
        power_wrapper_src = self.root_dir / "scripts" / "linux" / "pclink-power-wrapper"
        power_wrapper_dst = self.staging_dir / "usr" / "bin" / "pclink-power-wrapper"
        if power_wrapper_src.exists():
            shutil.copy2(power_wrapper_src, power_wrapper_dst)
            power_wrapper_dst.chmod(0o755)
            
        # Install power permissions test script
        test_script_src = self.root_dir / "scripts" / "linux" / "test-power-permissions"
        test_script_dst = self.staging_dir / "usr" / "bin" / "test-power-permissions"
        if test_script_src.exists():
            shutil.copy2(test_script_src, test_script_dst)
            test_script_dst.chmod(0o755)
        
        desktop_src = self.root_dir / "xyz.bytedz.PCLink.desktop"
        desktop_dst = self.staging_dir / "usr" / "share" / "applications" / "xyz.bytedz.PCLink.desktop"
        if desktop_src.exists():
            content = desktop_src.read_text(encoding='utf-8')
            desktop_dst.write_text(content.replace('\r\n', '\n').replace('\r', '\n'), encoding='utf-8')
            
        icon_src = self.root_dir / "src" / "pclink" / "assets" / "icon.png"
        icon_dst = self.staging_dir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "xyz.bytedz.PCLink.png"
        if icon_src.exists():
            shutil.copy2(icon_src, icon_dst)
            

            
        # Install systemd user service template
        service_template_src = self.root_dir / "scripts" / "linux" / "pclink.service.template"
        service_dst = self.staging_dir / "usr" / "lib" / "systemd" / "user" / "pclink.service"
        if service_template_src.exists():
            template_content = service_template_src.read_text()
            processed_content = template_content.replace("__EXEC_PATH__", "/usr/bin/pclink")
            processed_content = processed_content.replace("__WORKING_DIR__", "/usr/lib/pclink")
            service_dst.write_text(processed_content)
            

        # Install sudoers file for power commands
        sudoers_src = self.root_dir / "scripts" / "linux" / "pclink-sudoers"
        sudoers_dst = self.staging_dir / "etc" / "sudoers.d" / "pclink"
        if sudoers_src.exists():
            shutil.copy2(sudoers_src, sudoers_dst)
            sudoers_dst.chmod(0o440)
            
        for doc_file in ["README.md", "LICENSE", "CHANGELOG.md"]:
            doc_src = self.root_dir / doc_file
            if doc_src.exists():
                shutil.copy2(doc_src, self.staging_dir / "usr" / "share" / "doc" / "pclink" / doc_file)
                
        man_content = f""".TH PCLINK 1 "{VERSION}" "PCLink" "User Commands"
.SH NAME
pclink \\- Remote PC Control and File Management
.SH SYNOPSIS
.B pclink
[\\fIOPTIONS\\fR]
.SH DESCRIPTION
PCLink enables secure remote control and management of PCs from mobile devices.
Features include file browsing, process management, terminal access, media control,
and clipboard synchronization over HTTPS with API key authentication.
.SH OPTIONS
.TP
\\fB\\-\\-startup\\fR
Start in headless mode (system tray only)
.TP
\\fB\\-\\-help\\fR
Show help message and exit
.SH FILES
.TP
\\fI~/.config/pclink/\\fR
User configuration directory
.TP
\\fI~/.local/share/pclink/\\fR
User data directory
.SH AUTHOR
Azhar Zouhir <support@bytedz.xyz>
.SH SEE ALSO
Project homepage: https://github.com/BYTEDz/pclink
"""
        man_path = self.staging_dir / "usr" / "share" / "man" / "man1" / "pclink.1"
        man_path.write_text(man_content)
        
    def create_scripts(self):
        """Create package installation/removal scripts."""
        print("[SCRIPTS] Creating package scripts...")
        
        scripts_dir = self.build_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        
        postinst_content = """#!/bin/bash
set -e

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"

python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip

WHEEL_FILE=$(find "$INSTALL_DIR" -name "*.whl" | head -1)
if [ -z "$WHEEL_FILE" ]; then
    echo "ERROR: No wheel file found"
    exit 1
fi

"$VENV_DIR/bin/pip" install "$WHEEL_FILE"

# Test AppIndicator availability
echo "Testing AppIndicator availability..."
"$VENV_DIR/bin/python" -c "
import sys
print('Python path:', sys.path)
try:
    import gi
    print('✓ GI module imported successfully')
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3
    print('✓ AppIndicator3 is available - native tray menus will work')
except Exception as e:
    print('⚠ AppIndicator3 not available:', e)
    print('  PCLink will use fallback tray (right-click may not work)')
    print('  To fix: sudo apt install python3-gi gir1.2-appindicator3-0.1')
" || true

# Set up permissions and groups
# Try to determine the actual user (not root) who should get permissions
ACTUAL_USER=""
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
elif [ -n "$PKEXEC_UID" ]; then
    ACTUAL_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1)
elif [ "$USER" != "root" ]; then
    ACTUAL_USER="$USER"
fi

if [ -n "$ACTUAL_USER" ] && [ "$ACTUAL_USER" != "root" ]; then
    echo "Setting up permissions for user: $ACTUAL_USER"
    
    # Add user to plugdev group for hardware access
    if getent group plugdev >/dev/null 2>&1; then
        usermod -a -G plugdev "$ACTUAL_USER" 2>/dev/null || true
        echo "Added $ACTUAL_USER to plugdev group"
    fi
    
    # Add user to power group if it exists
    if getent group power >/dev/null 2>&1; then
        usermod -a -G power "$ACTUAL_USER" 2>/dev/null || true
        echo "Added $ACTUAL_USER to power group"
    fi
else
    echo "Warning: Could not determine user for group permissions"
    echo "To fix power commands manually, run: sudo usermod -a -G plugdev \$USER"
fi

# Validate sudoers file
if [ -f "/etc/sudoers.d/pclink" ]; then
    if visudo -c -f /etc/sudoers.d/pclink; then
        echo "✓ Sudoers file validated successfully"
    else
        echo "⚠ Sudoers file validation failed, removing it"
        rm -f /etc/sudoers.d/pclink
    fi
fi

# Test power wrapper availability
if [ -f "/usr/bin/pclink-power-wrapper" ]; then
    echo "✓ Power wrapper installed"
else
    echo "⚠ Power wrapper not found"
fi



# Enable systemd user service if systemd is available
if command -v systemctl >/dev/null 2>&1 && [ -f "/usr/lib/systemd/user/pclink.service" ]; then
    systemctl --global enable pclink.service 2>/dev/null || true
fi

# Update desktop database and icon cache
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
command -v mandb >/dev/null 2>&1 && mandb -q || true

echo "PCLink installed successfully!"
echo ""
echo "To start PCLink:"
echo "  pclink"
echo ""
echo "For power commands to work properly:"
echo "  1. Log out and log back in (to apply group permissions)"
echo "  2. Or run: newgrp plugdev"
echo "  3. Test with: test-power-permissions"
echo ""
echo "Web interface: https://localhost:8000/ui/"
"""
        
        postinst_path = scripts_dir / "postinst"
        postinst_path.write_text(postinst_content)
        postinst_path.chmod(0o755)
        
        prerm_content = """#!/bin/bash
set -e

# Stop systemd user service if running
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop pclink.service 2>/dev/null || true
    systemctl --user disable pclink.service 2>/dev/null || true
fi

# Stop any running PCLink processes
pkill -f pclink || true
"""
        
        prerm_path = scripts_dir / "prerm"
        prerm_path.write_text(prerm_content)
        prerm_path.chmod(0o755)
        
        postrm_content = """#!/bin/bash
set -e

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"

if [ -d "$VENV_DIR" ]; then
    rm -rf "$VENV_DIR"
fi

# Disable systemd user service globally
if command -v systemctl >/dev/null 2>&1; then
    systemctl --global disable pclink.service 2>/dev/null || true
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
"""
        
        postrm_path = scripts_dir / "postrm"
        postrm_path.write_text(postrm_content)
        postrm_path.chmod(0o755)
        
        return {
            "postinst": postinst_path,
            "prerm": prerm_path,
            "postrm": postrm_path,
        }
        
    def build_package(self, package_type: str):
        """Build a package using FPM."""
        print(f"[BUILD] Building {package_type.upper()} package...")
        
        if package_type not in self.distributions:
            raise ValueError(f"Unsupported package type: {package_type}")
            
        config = self.distributions[package_type]
        scripts = self.create_scripts()
        
        if package_type == "deb":
            output_name = f"{self.package_name}_{VERSION}_{self.metadata['architecture']}.deb"
        elif package_type == "rpm":
            output_name = f"{self.package_name}-{VERSION}-1.{self.metadata['architecture']}.rpm"
        elif package_type == "pacman":
            output_name = f"{self.package_name}-{VERSION}-1-{self.metadata['architecture']}.pkg.tar.xz"
        elif package_type == "freebsd":
            output_name = f"{self.package_name}-{VERSION}.txz"
        else:
            output_name = f"{self.package_name}-{VERSION}.{package_type}"
            
        output_path = self.releases_dir / output_name
        self.releases_dir.mkdir(exist_ok=True)
        
        if output_path.exists():
            output_path.unlink()
            print(f"[INFO] Removed existing package: {output_path}")
        
        cmd = [
            "fpm",
            "-s", "dir",
            "-t", package_type,
            "-n", self.metadata["name"],
            "-v", self.metadata["version"],
            "--description", self.metadata["description"],
            "--maintainer", self.metadata["maintainer"],
            "--vendor", self.metadata["vendor"],
            "--license", self.metadata["license"],
            "--url", self.metadata["url"],
            "--category", self.metadata["category"],
            "-a", self.metadata["architecture"],
            "-p", str(output_path),
            "--force",
        ]
        
        for dep in config["depends"]:
            cmd.extend(["-d", dep])
            
        for conflict in config["conflicts"]:
            cmd.extend(["--conflicts", conflict])
            
        for provides in config["provides"]:
            cmd.extend(["--provides", provides])
            
        for replaces in config["replaces"]:
            cmd.extend(["--replaces", replaces])
            
        if package_type in ["deb", "rpm"]:
            cmd.extend(["--after-install", str(scripts["postinst"])])
            cmd.extend(["--before-remove", str(scripts["prerm"])])
            cmd.extend(["--after-remove", str(scripts["postrm"])])
            
        cmd.extend(["-C", str(self.staging_dir)])
        cmd.append(".")
        
        print(f"[RUN] {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
            print(f"[SUCCESS] {package_type.upper()} package created: {output_path}")
            
            if not output_path.exists():
                raise RuntimeError(f"Package file not found after build: {output_path}")
            
            package_size = output_path.stat().st_size / (1024 * 1024)
            print(f"[INFO] Package size: {package_size:.1f} MB")
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] FPM command failed:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise RuntimeError(f"Failed to build {package_type} package")
        except subprocess.TimeoutExpired:
            print(f"[ERROR] FPM command timed out after 5 minutes")
            raise RuntimeError(f"Build timeout for {package_type} package")
        
    def build_all(self, package_types: list = None):
        """Build packages for all specified types."""
        if package_types is None:
            package_types = ["deb", "rpm"]
            
        print(f"--- PCLink FPM Builder v{VERSION} ---")
        print(f"Building packages: {', '.join(package_types)}")
        
        if not self.verify_build_environment():
            return False
        
        available_types = []
        for pkg_type in package_types:
            if pkg_type == "deb" and shutil.which("dpkg"):
                available_types.append(pkg_type)
            elif pkg_type == "rpm" and (shutil.which("rpm") or shutil.which("rpmbuild")):
                available_types.append(pkg_type)
            elif pkg_type in ["pacman", "freebsd"]:
                available_types.append(pkg_type)
            else:
                print(f"[WARNING] Skipping {pkg_type} - required tools not available")
        
        if not available_types:
            print("[ERROR] No package types can be built with current system")
            return False
        
        print(f"[INFO] Building package types: {', '.join(available_types)}")
        
        try:
            self.clean()
            self.create_staging_structure()
            self.install_application_files()
            
            built_packages = []
            failed_packages = []
            
            for package_type in available_types:
                try:
                    print(f"\n[START] Building {package_type.upper()} package...")
                    package_path = self.build_package(package_type)
                    built_packages.append(package_path)
                except Exception as e:
                    print(f"[ERROR] Failed to build {package_type} package: {e}")
                    failed_packages.append((package_type, str(e)))
            
            print(f"\n--- Build Summary ---")
            if built_packages:
                print(f"[SUCCESS] Built {len(built_packages)} package(s):")
                for package in built_packages:
                    print(f"  ✓ {package}")
            
            if failed_packages:
                print(f"[FAILED] {len(failed_packages)} package(s) failed:")
                for pkg_type, error in failed_packages:
                    print(f"  ✗ {pkg_type}: {error}")
            
            return len(built_packages) > 0
            
        except Exception as e:
            print(f"[ERROR] Build process failed: {e}")
            return False

def main():
    try:
        builder = FPMBuilder()
        success = builder.build_all(["deb", "rpm"])
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
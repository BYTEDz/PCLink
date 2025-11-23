# filename: scripts/build_nfpm.py (Updated to use NFPM/GoReleaser approach)

#!/usr/bin/env python3
"""
PCLink NFPM Package Pre-Builder

Prepares the staging directory and generates the nfpm.yaml config and
maintainer scripts for package creation via nfpm or GoReleaser.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import yaml
from pathlib import Path

# Add src to path for version info
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

try:
    from pclink.core.version import version_info
    VERSION = version_info.version
except ImportError:
    VERSION = "2.3.0"

class NFPMBuilder:
    def __init__(self):
        self.root_dir = Path.cwd()
        self.build_dir = self.root_dir / "build" / "nfpm"
        self.releases_dir = self.root_dir / "releases"
        self.package_name = "pclink"
        self.staging_dir = self.build_dir / "staging"
        self.nfpm_config_path = self.root_dir / "nfpm.yaml"
        
        # Package metadata (extracted from pyproject.toml logic)
        self.metadata = {
            "name": self.package_name,
            "version": VERSION,
            "description": "Cross-platform desktop app for secure remote PC control and management.",
            "maintainer": "Azhar Zouhir <support@bytedz.xyz>",
            "homepage": "https://github.com/BYTEDz/PCLink",
            "license": "AGPL-3.0-or-later",
            "architecture": "amd64",
        }
        
    def verify_python_environment(self):
        """Verify basic Python environment for build script execution."""
        if sys.version_info < (3, 8):
            print(f"[ERROR] Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")
            return False
        print("[INFO] Python environment OK for pre-packaging tasks.")
        return True
        
    def clean(self):
        """Clean previous build artifacts."""
        print("[CLEAN] Removing previous build artifacts...")
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
        
        # Use sys.executable to ensure we use the same Python interpreter
        cmd = [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), "."]
        try:
            subprocess.run(cmd, check=True, cwd=self.root_dir, capture_output=True, text=True)
            print(f"[OK] Wheel build completed")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Wheel build failed:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise RuntimeError("Wheel creation failed")
        
        wheel_files = list(wheel_dir.glob("*.whl"))
        if not wheel_files:
            raise RuntimeError("No wheel file was created")
        
        wheel_path = wheel_files[0]
        print(f"[OK] Created wheel: {wheel_path.name}")
        return wheel_path
        
    def install_application_files(self):
        """Install the application files to staging directory."""
        print("[FILES] Installing application files to staging...")
        
        wheel_path = self.create_wheel()
        wheel_dest = self.staging_dir / "usr" / "lib" / "pclink" / wheel_path.name
        shutil.copy2(wheel_path, wheel_dest)
        
        # --- Launcher Script ---
        launcher_content = f"""#!/bin/bash
# PCLink Launcher Script
INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="/tmp/pclink-launcher.log"

log() {{ echo "$(date): $1" >> "$LOG_FILE"; }}
log "PCLink launcher started with args: $@"

if [ ! -d "$VENV_DIR" ]; then
    log "ERROR: Virtual environment not found at $VENV_DIR"
    echo "Error: PCLink virtual environment not found. Try reinstalling the package."
    exit 1
fi

"$VENV_DIR/bin/pclink" "$@" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${{PIPESTATUS[0]}}

log "PCLink exited with code: $EXIT_CODE"
exit $EXIT_CODE
"""
        launcher_path = self.staging_dir / "usr" / "bin" / "pclink"
        launcher_path.write_text(launcher_content, encoding='utf-8')
        launcher_path.chmod(0o755)
        
        # --- Sudoers File (from template) ---
        sudoers_src = self.root_dir / "scripts/linux/pclink-sudoers"
        sudoers_dst = self.staging_dir / "etc" / "sudoers.d" / "pclink"
        if sudoers_src.exists():
            shutil.copy2(sudoers_src, sudoers_dst)
        else:
            # Fallback content if file is missing
            sudoers_content = """# PCLink power management permissions
# Allow members of plugdev group to execute power commands without password
%plugdev ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff
%plugdev ALL=(ALL) NOPASSWD: /usr/bin/systemctl reboot
%plugdev ALL=(ALL) NOPASSWD: /usr/bin/systemctl suspend
%plugdev ALL=(ALL) NOPASSWD: /sbin/poweroff
%plugdev ALL=(ALL) NOPASSWD: /sbin/reboot
%plugdev ALL=(ALL) NOPASSWD: /sbin/shutdown
%plugdev ALL=(ALL) NOPASSWD: /usr/sbin/pm-suspend
"""
            sudoers_dst.write_text(sudoers_content, encoding='utf-8')
        # Note: chmod(0o440) is applied via nfpm.yaml file_info
        
        # --- Copy other resources (Simplified logic) ---
        resources = [
            ("scripts/linux/pclink-power-wrapper", "usr/bin/pclink-power-wrapper"),
            ("scripts/linux/test-power-permissions", "usr/bin/test-power-permissions"),
            ("xyz.bytedz.PCLink.desktop", "usr/share/applications/xyz.bytedz.PCLink.desktop"),
            ("src/pclink/assets/icon.png", "usr/share/icons/hicolor/256x256/apps/xyz.bytedz.PCLink.png"),
            ("scripts/linux/pclink.service.template", "usr/lib/systemd/user/pclink.service"),
        ]
        
        for src_rel, dst_rel in resources:
            src = self.root_dir / src_rel
            dst = self.staging_dir / dst_rel
            if src.exists():
                shutil.copy2(src, dst)
                if 'bin' in dst_rel:
                    dst.chmod(0o755)
                elif 'desktop' in dst_rel:
                    # Clean up line endings for desktop files
                    content = dst.read_text(encoding='utf-8')
                    dst.write_text(content.replace('\r\n', '\n').replace('\r', '\n'), encoding='utf-8')

        # Man page and Docs
        man_content = f""".TH PCLINK 1 "{VERSION}" "PCLink" "User Commands"
.SH NAME
pclink \\- Remote PC Control and File Management
.SH SYNOPSIS
.B pclink
[\\fIOPTIONS\\fR]
.SH DESCRIPTION
PCLink enables secure remote control and management of PCs from mobile devices.
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
.SH AUTHOR
Azhar Zouhir <support@bytedz.xyz>
"""
        man_path = self.staging_dir / "usr" / "share" / "man" / "man1" / "pclink.1"
        man_path.write_text(man_content, encoding='utf-8')

        for doc_file in ["README.md", "LICENSE", "CHANGELOG.md"]:
            doc_src = self.root_dir / doc_file
            if doc_src.exists():
                shutil.copy2(doc_src, self.staging_dir / "usr" / "share" / "doc" / "pclink" / doc_file)
        
    def create_scripts(self):
        """Create package installation/removal scripts."""
        print("[SCRIPTS] Creating final maintainer scripts...")
        
        scripts_dir = self.build_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        
        # --- postinst content (FIXED: Better detection and no set -e) ---
        postinst_content = """#!/bin/bash
# Note: Removed 'set -e' to prevent package manager corruption on non-fatal errors

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"

echo "=== PCLink postinst: action='$1', old_version='$2' ==="

# --- Core Setup Function ---
install_pclink() {
    local IS_UPGRADE="$1"
    
    if [ "$IS_UPGRADE" = "true" ]; then
        echo "PCLink: Upgrading from version $2..."
    else
        echo "PCLink: Fresh installation..."
    fi

    # For upgrades, try to preserve the venv if possible, only recreate if broken
    if [ "$IS_UPGRADE" = "true" ] && [ -d "$VENV_DIR" ]; then
        echo "Checking existing virtual environment..."
        if "$VENV_DIR/bin/python" -c "import sys; sys.exit(0)" 2>/dev/null; then
            echo "Existing venv is functional, upgrading in place..."
            "$VENV_DIR/bin/pip" install --upgrade pip 2>/dev/null || true
        else
            echo "Existing venv is broken, recreating..."
            rm -rf "$VENV_DIR"
        fi
    fi
    
    # Create venv if it doesn't exist
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment..."
        python3 -m venv --system-site-packages "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --upgrade pip 2>/dev/null || true
    fi

    # Find and install the wheel - use the newest one if multiple exist
    WHEEL_FILE=$(find "$INSTALL_DIR" -name "*.whl" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -z "$WHEEL_FILE" ]; then
        # Fallback to simple find if printf not available
        WHEEL_FILE=$(find "$INSTALL_DIR" -name "*.whl" -type f | head -1)
    fi
    
    if [ -z "$WHEEL_FILE" ] || [ ! -f "$WHEEL_FILE" ]; then
        echo "ERROR: No wheel file found in $INSTALL_DIR"
        ls -la "$INSTALL_DIR" || true
        return 1
    fi

    echo "PCLink: Installing package from $WHEEL_FILE..."
    
    # Clean up any old wheel files first (keep only the one we're installing)
    find "$INSTALL_DIR" -name "*.whl" -type f ! -path "$WHEEL_FILE" -delete 2>/dev/null || true
    
    # Install/upgrade the wheel (--force-reinstall ensures clean upgrade)
    if ! "$VENV_DIR/bin/pip" install --force-reinstall --no-deps "$WHEEL_FILE"; then
        echo "ERROR: Failed to install wheel"
        return 1
    fi

    # Test AppIndicator availability
    echo "Testing AppIndicator availability..."
    "$VENV_DIR/bin/python" -c "
import sys
try:
    import gi
    gi.require_version('AppIndicator3', '0.1')
    print('✓ AppIndicator3 is available - native tray menus will work')
except Exception as e:
    print('⚠ AppIndicator3 not available:', e)
    print('  To fix: sudo apt install python3-gi gir1.2-appindicator3-0.1')
" || true

    # Only set up user permissions on fresh install, not upgrades
    if [ "$IS_UPGRADE" != "true" ]; then
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
            
            if getent group plugdev >/dev/null 2>&1; then
                usermod -a -G plugdev "$ACTUAL_USER" 2>/dev/null || true
                echo "✓ Added $ACTUAL_USER to plugdev group"
            fi
            
            if getent group power >/dev/null 2>&1; then
                usermod -a -G power "$ACTUAL_USER" 2>/dev/null || true
                echo "✓ Added $ACTUAL_USER to power group"
            fi
        fi
    fi

    # Validate sudoers file
    if [ -f "/etc/sudoers.d/pclink" ]; then
        if command -v visudo >/dev/null 2>&1; then
            if visudo -c -f /etc/sudoers.d/pclink >/dev/null 2>&1; then
                echo "✓ Sudoers file validated"
            else
                echo "⚠ Sudoers file validation failed, removing it"
                rm -f /etc/sudoers.d/pclink
            fi
        fi
    fi

    # Enable systemd user service (safe for both install and upgrade)
    if command -v systemctl >/dev/null 2>&1 && [ -f "/usr/lib/systemd/user/pclink.service" ]; then
        systemctl --global enable pclink.service 2>/dev/null || true
        systemctl daemon-reload 2>/dev/null || true
    fi

    # Update system caches
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
    command -v mandb >/dev/null 2>&1 && mandb -q 2>/dev/null || true

    if [ "$IS_UPGRADE" = "true" ]; then
        echo "✓ PCLink upgraded successfully!"
    else
        echo "✓ PCLink installed successfully!"
        echo ""
        echo "To start PCLink: pclink"
        echo "Web interface: https://localhost:38080/ui/"
    fi
    
    return 0
}
# --- End Core Setup Function ---

# Standard DPKG postinst logic
case "$1" in
    configure)
        # Verify installation directory exists
        if [ ! -d "$INSTALL_DIR" ]; then
            echo "ERROR: Installation directory $INSTALL_DIR does not exist!"
            echo "This may indicate a failed or incomplete package installation."
            exit 1
        fi
        
        # Check if wheel file exists
        WHEEL_COUNT=$(find "$INSTALL_DIR" -name "*.whl" 2>/dev/null | wc -l)
        if [ "$WHEEL_COUNT" -eq 0 ]; then
            echo "ERROR: No wheel file found in $INSTALL_DIR"
            echo "Package installation is incomplete. Please reinstall."
            exit 1
        fi
        
        # Check if this is an upgrade (previous version passed as $2)
        if [ -n "$2" ] && [ "$2" != "<unknown>" ]; then
            echo "PCLink: Detected upgrade from version $2"
            install_pclink "true" "$2" || exit 1
        else
            echo "PCLink: Detected fresh installation"
            install_pclink "false" "" || exit 1
        fi
        ;;
    
    abort-upgrade|abort-remove|abort-deconfigure)
        echo "PCLink: Package operation aborted: $1"
        ;;
    
    *)
        echo "PCLink: postinst called with unknown argument: $1"
        ;;
esac

echo "=== PCLink postinst completed successfully ==="
exit 0
"""
        
        postinst_path = scripts_dir / "postinst"
        postinst_path.write_text(postinst_content, encoding='utf-8')
        postinst_path.chmod(0o755)
        
        # --- prerm content (FIXED: Better detection and logging) ---
        prerm_content = """#!/bin/bash
# Note: DO NOT use 'set -e' - failures must not block package operations

echo "=== PCLink prerm: action='$1', old_version='$2', new_version='$3' ==="

# Standard DPKG prerm logic
case "$1" in
    remove)
        echo "PCLink: Stopping services for removal..."
        
        # Try to stop user services gracefully (but don't fail if they're not running)
        if command -v systemctl >/dev/null 2>&1; then
            # Stop all user instances
            for user_dir in /run/user/*/; do
                user_id=$(basename "$user_dir")
                if [ -n "$user_id" ] && [ "$user_id" != "*" ]; then
                    systemctl --user --machine="${user_id}@.host" stop pclink.service 2>/dev/null || true
                fi
            done
        fi
        
        # Kill any remaining PCLink processes (but don't fail if none exist)
        # Match against the installation directory to avoid killing apt or this script
        pkill -f "/usr/lib/pclink" 2>/dev/null || true
        
        # Give processes time to terminate gracefully
        sleep 1
        ;;
    
    upgrade|deconfigure)
        # During upgrade, do NOT stop services - let the new version handle it
        echo "PCLink: Preparing for upgrade (keeping services running)..."
        ;;
    
    failed-upgrade)
        echo "PCLink: Handling failed upgrade..."
        ;;
    
    *)
        echo "PCLink: prerm called with unknown argument: $1"
        ;;
esac

echo "=== PCLink prerm completed ==="
exit 0
"""
        
        prerm_path = scripts_dir / "prerm"
        prerm_path.write_text(prerm_content, encoding='utf-8')
        prerm_path.chmod(0o755)
        
        # --- postrm content (FIXED: Better logging and detection) ---
        postrm_content = """#!/bin/bash
# Note: DO NOT use 'set -e' - failures must not block package operations

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"

echo "=== PCLink postrm: action='$1', old_version='$2' ==="

# Standard DPKG postrm logic
case "$1" in
    remove)
        echo "PCLink: Cleaning up installation..."
        
        # Remove virtual environment
        if [ -d "$VENV_DIR" ]; then
            echo "Removing virtual environment..."
            rm -rf "$VENV_DIR" 2>/dev/null || true
        fi
        
        # Remove wheel files
        if [ -d "$INSTALL_DIR" ]; then
            echo "Removing wheel files..."
            find "$INSTALL_DIR" -name "*.whl" -type f -delete 2>/dev/null || true
            
            # Remove installation directory if empty
            rmdir "$INSTALL_DIR" 2>/dev/null || true
        fi

        # Disable systemd user service globally
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --global disable pclink.service 2>/dev/null || true
            systemctl daemon-reload 2>/dev/null || true
        fi
        ;;
    
    purge)
        echo "PCLink: Purging configuration..."
        
        # Remove everything including config and wheels
        if [ -d "$INSTALL_DIR" ]; then
            echo "Removing installation directory..."
            rm -rf "$INSTALL_DIR" 2>/dev/null || true
        fi
        rm -f "/etc/sudoers.d/pclink" 2>/dev/null || true
        
        # Disable and remove systemd service
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --global disable pclink.service 2>/dev/null || true
            systemctl daemon-reload 2>/dev/null || true
        fi
        
        # Remove user config directories (optional - be careful here)
        # Uncomment if you want to remove user data on purge:
        # rm -rf /home/*/.config/pclink 2>/dev/null || true
        ;;
    
    upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
        # During upgrade, do NOT remove anything
        echo "PCLink: Package operation '$1' (no cleanup needed)"
        ;;
    
    *)
        echo "PCLink: postrm called with unknown argument: $1"
        ;;
esac

# Update system databases (safe for all operations)
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
command -v mandb >/dev/null 2>&1 && mandb -q 2>/dev/null || true

echo "=== PCLink postrm completed ==="
exit 0
"""
        
        postrm_path = scripts_dir / "postrm"
        postrm_path.write_text(postrm_content, encoding='utf-8')
        postrm_path.chmod(0o755)
        
        return {
            "postinst": postinst_path,
            "prerm": prerm_path,
            "postrm": postrm_path,
        }
        
    def generate_nfpm_config(self):
        """Generates the nfpm.yaml configuration file."""
        print("[NFPM] Generating nfpm.yaml configuration...")
        
        nfpm_config = {
            "name": self.metadata["name"],
            "arch": self.metadata["architecture"],
            "platform": "linux",
            "version": self.metadata["version"],
            "section": "net",
            "priority": "optional",
            "maintainer": self.metadata["maintainer"],
            "description": self.metadata["description"],
            "homepage": self.metadata["homepage"],
            "license": self.metadata["license"],
            
            "depends": [
                "python3 (>= 3.8)",
                "python3-pip",
                "python3-venv",
                "libxcb-cursor0", "libxcb-xinerama0", "libxcb-randr0",
                "libxcb-render-util0", "libxcb-keysyms1", "libxcb-image0",
                "libxcb-icccm4", "python3-gi", "gir1.2-appindicator3-0.1",
                "gir1.2-gtk-3.0", "systemd | sysvinit-core | runit", "dbus",
                "procps",
            ],
            
            "contents": [
                {"src": "build/nfpm/staging/usr/lib/pclink", "dst": "/usr/lib/pclink"},
                {"src": "build/nfpm/staging/usr/bin/pclink", "dst": "/usr/bin/pclink"},
                {"src": "build/nfpm/staging/usr/bin/pclink-power-wrapper", "dst": "/usr/bin/pclink-power-wrapper"},
                {"src": "build/nfpm/staging/usr/bin/test-power-permissions", "dst": "/usr/bin/test-power-permissions"},
                {"src": "build/nfpm/staging/usr/share/applications/xyz.bytedz.PCLink.desktop", "dst": "/usr/share/applications/xyz.bytedz.PCLink.desktop"},
                {"src": "build/nfpm/staging/usr/share/icons/hicolor/256x256/apps/xyz.bytedz.PCLink.png", "dst": "/usr/share/icons/hicolor/256x256/apps/xyz.bytedz.PCLink.png"},
                {"src": "build/nfpm/staging/usr/share/man/man1/pclink.1", "dst": "/usr/share/man/man1/pclink.1"},
                {"src": "build/nfpm/staging/usr/lib/systemd/user/pclink.service", "dst": "/usr/lib/systemd/user/pclink.service"},
                {
                    "src": "build/nfpm/staging/etc/sudoers.d/pclink", 
                    "dst": "/etc/sudoers.d/pclink",
                    "file_info": {"mode": 0o440}
                },
                # Include documentation files
                {"src": "build/nfpm/staging/usr/share/doc/pclink", "dst": "/usr/share/doc/pclink"},
            ],
            
            "scripts": {
                "postinstall": "build/nfpm/scripts/postinst",
                "preremove": "build/nfpm/scripts/prerm",
                "postremove": "build/nfpm/scripts/postrm",
            },
        }
        
        with open(self.nfpm_config_path, 'w') as f:
            yaml.safe_dump(nfpm_config, f, default_flow_style=False)
        
        print(f"[OK] Generated NFPM config at {self.nfpm_config_path}")

    def build_all(self):
        """Prepare files and NFPM config for external packaging."""
        print(f"--- PCLink Pre-Packager v{VERSION} ---")
        
        if not self.verify_python_environment():
            return False
        
        try:
            self.clean()
            self.create_staging_structure()
            self.install_application_files()
            self.create_scripts()
            self.generate_nfpm_config()
            
            print("\n--- Preparation Complete ---")
            print("To build packages, run NFPM from the project root:")
            print("  nfpm package -f nfpm.yaml")
            print("Or use GoReleaser.")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Build process failed: {e}")
            return False

def main():
    try:
        builder = NFPMBuilder()
        success = builder.build_all()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
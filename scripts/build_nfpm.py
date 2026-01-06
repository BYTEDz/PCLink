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
        
    def install_application_files(self, existing_wheel_path=None):
        """Install the application files to staging directory."""
        print("[FILES] Installing application files to staging...")
        
        if existing_wheel_path:
            wheel_path = Path(existing_wheel_path)
            if not wheel_path.exists():
                raise RuntimeError(f"Provided wheel path does not exist: {wheel_path}")
            print(f"[WHEEL] Using existing wheel: {wheel_path.name}")
        else:
            wheel_path = self.create_wheel()

        wheel_dest = self.staging_dir / "usr" / "lib" / "pclink" / wheel_path.name
        shutil.copy2(wheel_path, wheel_dest)
        
        # --- Launcher Script ---
        launcher_content = f"""#!/bin/bash
# PCLink Launcher Script
INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
# Simple log for debugging
LOG_FILE="/tmp/pclink-launcher.log"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: PCLink virtual environment not found at $VENV_DIR"
    exit 1
fi

# Execute the application
"$VENV_DIR/bin/pclink" "$@"
EXIT_CODE=$?

exit $EXIT_CODE
"""
        launcher_path = self.staging_dir / "usr" / "bin" / "pclink"
        launcher_path.write_text(launcher_content, encoding='utf-8')
        launcher_path.chmod(0o755)
        
        # --- Sudoers File (from template) ---
        sudoers_src = self.root_dir / "scripts/linux/pclink-sudoers"
        sudoers_dst = self.staging_dir / "etc" / "sudoers.d" / "pclink"
        if sudoers_src.exists():
            content = sudoers_src.read_text(encoding='utf-8')
            sudoers_dst.write_text(content.replace('\r\n', '\n').replace('\r', '\n'), encoding='utf-8')
        else:
            # Fallback content
            sudoers_content = """# PCLink power management permissions
%plugdev ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff
%plugdev ALL=(ALL) NOPASSWD: /usr/bin/systemctl reboot
%plugdev ALL=(ALL) NOPASSWD: /usr/bin/systemctl suspend
%plugdev ALL=(ALL) NOPASSWD: /sbin/poweroff
%plugdev ALL=(ALL) NOPASSWD: /sbin/reboot
%plugdev ALL=(ALL) NOPASSWD: /sbin/shutdown
%plugdev ALL=(ALL) NOPASSWD: /usr/sbin/pm-suspend
"""
            sudoers_dst.write_text(sudoers_content.replace('\r\n', '\n'), encoding='utf-8')
        
        # --- Copy other resources ---
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
                
                # Fix line endings and placeholders
                if dst_rel.endswith(('.desktop', '.service', 'pclink-power-wrapper', 'test-power-permissions')):
                    content = dst.read_text(encoding='utf-8')
                    # ENFORCE Unix line endings
                    content = content.replace('\r\n', '\n').replace('\r', '\n')
                    
                    # Fix Service File Placeholders
                    if dst_rel.endswith("pclink.service"):
                        print("[FIX] Replacing placeholders in service file...")
                        content = content.replace('__EXEC_PATH__', '/usr/bin/pclink')
                        content = content.replace('__WORKING_DIR__', '%h')
                        # Remove User/Group from user service as they are invalid
                        content = content.replace('User=%i\n', '')
                        content = content.replace('Group=%i\n', '')
                        # Relax ProtectHome for file management
                        content = content.replace('ProtectHome=read-only', 'ProtectHome=false')

                    dst.write_text(content, encoding='utf-8')

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
        print("[SCRIPTS] Creating final maintainer scripts (SAFE MODE)...")
        
        scripts_dir = self.build_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        
        # --- postinst content ---
        # SAFE: No dnf install, no set -e, strict error handling
        postinst_content = """#!/bin/bash
# Note: Removed 'set -e' to prevent package manager corruption on non-fatal errors

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="/tmp/pclink_install.log"

# Log function that prints to stdout AND file
log() { 
    echo "$(date) - PCLink: $1" | tee -a "$LOG_FILE"
}

# Error function that prints to stderr
error() {
    echo "ERROR: $1" | tee -a "$LOG_FILE" >&2
}

echo "=== PCLink postinst: action='$1', old_version='$2' ==="
log "Starting postinst action=$1 old_version=$2"

case "$1" in
    configure|1|2)
        log "Configuring PCLink..."
        
        if [ ! -d "$INSTALL_DIR" ]; then
            error "Install dir missing ($INSTALL_DIR). Package may be broken."
            exit 0 
        fi
        
        # --- Python Venv Setup ---
        # We try to create/update venv, but we catch errors
        if [ ! -d "$VENV_DIR" ]; then
            log "Creating virtual environment..."
            if command -v python3 >/dev/null; then
                # Use --without-pip to potentially speed up if pip is not needed/bundled, 
                # but we usually need pip.
                python3 -m venv --system-site-packages "$VENV_DIR" >> "$LOG_FILE" 2>&1 
                if [ $? -ne 0 ]; then
                    error "Failed to create virtual environment."
                    echo "Please check $LOG_FILE for details."
                fi
            else
                error "python3 not found, venv creation skipped."
            fi
        fi
        
        # Install Wheel
        # Find wheel file - robustness for filenames with spaces/weird chars
        WHEEL_FILE=$(find "$INSTALL_DIR" -maxdepth 1 -name "*.whl" -type f | head -1)
        
        if [ -f "$WHEEL_FILE" ] && [ -f "$VENV_DIR/bin/pip" ]; then
            log "Installing wheel: $WHEEL_FILE"
            # Force reinstall to ensure we overwrite any old files. 
            # We capture output but print errors on failure.
            if ! "$VENV_DIR/bin/pip" install --no-warn-script-location --force-reinstall "$WHEEL_FILE" >> "$LOG_FILE" 2>&1; then
                error "Wheel install failed."
                echo "Detailed pip error log in $LOG_FILE"
                error "Installation might be incomplete. Check internet connection if dependencies are missing."
                
                # Emergency fallback: Try installing WITHOUT dependencies?
                log "Attempting fallback: Install without dependencies..."
                "$VENV_DIR/bin/pip" install --no-deps --no-warn-script-location --force-reinstall "$WHEEL_FILE" >> "$LOG_FILE" 2>&1
            fi
        else
            error "Wheel file or pip missing. Wheel=$WHEEL_FILE"
        fi
        
        # --- Permissions ---
        # Only setup if we are root
        if [ "$(id -u)" -eq 0 ]; then
             # Validate sudoers file
            if [ -f "/etc/sudoers.d/pclink" ]; then
                chmod 440 /etc/sudoers.d/pclink
            fi
        fi

        # --- System Updates ---
        log "Updating system caches..."
        command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
        command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
        
        # Enable service globally (optional, purely for convenience)
        if command -v systemctl >/dev/null 2>&1; then
             # We can't enable user services for ALL users easily, so we typically rely on presets
             # or users doing `systemctl --user enable pclink`
             true
        fi
        
        log "Configuration complete."
        ;;
    
    *)
        log "postinst called with unknown argument: $1"
        ;;
esac
exit 0
"""
        
        postinst_path = scripts_dir / "postinst"
        # CRITICAL: Write with newline='\n' to force LF line endings on Windows
        with open(postinst_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(postinst_content.strip())
        postinst_path.chmod(0o755)
        
        # --- prerm content ---
        # SAFE: Always exit 0, never block removal
        prerm_content = """#!/bin/bash
# Note: DO NOT use 'set -e' - failures must not block package operations

LOG_FILE="/tmp/pclink_install.log"
log() { echo "$(date) - PCLink: $1" | tee -a "$LOG_FILE"; }

echo "=== PCLink prerm: action='$1', old_version='$2', new_version='$3' ==="

# Standard Multi-Distro prerm logic
case "$1" in
    remove|0)
        log "Stopping services for removal..."
        
        # Try to stop user services gracefully
        if command -v systemctl >/dev/null 2>&1; then
            # Stop all user instances
            for user_dir in /run/user/*/; do
                user_id=$(basename "$user_dir")
                if [ -n "$user_id" ] && [ "$user_id" != "*" ]; then
                    systemctl --user --machine="${user_id}@.host" stop pclink.service 2>/dev/null || true
                fi
            done
        fi
        
        # Kill any remaining PCLink processes
        pkill -f "/usr/lib/pclink" 2>/dev/null || true
        sleep 1
        ;;
    
    upgrade|deconfigure|1)
        # During upgrade, do NOT stop services
        log "Preparing for upgrade (keeping services running)..."
        ;;
    
    failed-upgrade)
        log "Handling failed upgrade..."
        ;;
    
    *)
        log "prerm called with unknown argument: $1"
        ;;
esac

log "prerm completed"
exit 0
"""
        
        prerm_path = scripts_dir / "prerm"
        # CRITICAL: Write with newline='\n' to force LF line endings on Windows
        with open(prerm_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(prerm_content.strip())
        prerm_path.chmod(0o755)
        
        # --- postrm content ---
        # SAFE: Cleanup what we can, ignore the rest
        postrm_content = """#!/bin/bash
# Note: DO NOT use 'set -e' - failures must not block package operations

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="/tmp/pclink_install.log"
log() { echo "$(date) - PCLink: $1" | tee -a "$LOG_FILE"; }

echo "=== PCLink postrm: action='$1', old_version='$2' ==="
log "Starting postrm action=$1"

# Standard Multi-Distro postrm logic
case "$1" in
    remove|0)
        log "Cleaning up installation..."
        
        # Remove virtual environment
        if [ -d "$VENV_DIR" ]; then
            log "Removing virtual environment..."
            rm -rf "$VENV_DIR" 2>/dev/null || true
        fi
        
        # Remove wheel files
        if [ -d "$INSTALL_DIR" ]; then
            log "Removing wheel files..."
            find "$INSTALL_DIR" -name "*.whl" -type f -delete 2>/dev/null || true
            rmdir "$INSTALL_DIR" 2>/dev/null || true
        fi

        # Disable systemd user service globally
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --global disable pclink.service 2>/dev/null || true
            systemctl daemon-reload 2>/dev/null || true
        fi
        ;;
    
    purge)
        log "Purging configuration..."
        
        # Remove everything including config and wheels
        if [ -d "$INSTALL_DIR" ]; then
            log "Removing installation directory..."
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
        log "Package operation '$1' (no cleanup needed)"
        ;;
    
    *)
        log "postrm called with unknown argument: $1"
        ;;
esac

# Update system databases (safe for all operations)
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
command -v mandb >/dev/null 2>&1 && mandb -q 2>/dev/null || true

log "postrm completed"
exit 0
"""
        
        postrm_path = scripts_dir / "postrm"
        # CRITICAL: Write with newline='\n' to force LF line endings on Windows
        with open(postrm_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(postrm_content.strip())
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
                "gir1.2-gtk-3.0",
                "systemd | sysvinit-core | runit", "dbus",
                "procps",
            ],

            "overrides": {
                "rpm": {
                    "depends": [
                        "python3 >= 3.8",
                        "systemd",
                        "dbus",
                    ],
                    "recommends": [
                        "python3-pip",
                        "xcb-util-cursor",
                        "libxcb",
                        "xcb-util-renderutil",
                        "xcb-util-keysyms",
                        "xcb-util-image",
                        "xcb-util-wm",
                        "python3-gobject",
                        "libappindicator-gtk3",
                        "gtk3",
                        "procps-ng",
                        "python3-devel",
                        "gcc",
                        "libayatana-appindicator-gtk3",
                        "wl-clipboard",
                        "gnome-screenshot",
                    ]
                }
            },
            
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

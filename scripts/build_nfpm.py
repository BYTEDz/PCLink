# filename: scripts/build_nfpm.py (Updated to use NFPM/GoReleaser approach)

#!/usr/bin/env python3
"""
PCLink NFPM Package Pre-Builder

Prepares the staging directory and generates the nfpm.yaml config and
maintainer scripts for package creation via nfpm or GoReleaser.
"""

import shutil
import subprocess
import sys
from pathlib import Path

# Add src to path for version info
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    from pclink.core.version import version_info

    VERSION = version_info.version
except ImportError:
    VERSION = "2.3.0"


class NFPMBuilder:
    def __init__(self, architecture: str = "amd64"):
        self.root_dir = Path.cwd()
        self.build_dir = self.root_dir / "build" / "nfpm"
        self.releases_dir = self.root_dir / "releases"
        self.package_name = "pclink"
        self.staging_dir = self.build_dir / "staging"
        self.nfpm_config_path = self.root_dir / "nfpm.yaml"

        # Package metadata (architecture is now configurable)
        self.metadata = {
            "name": self.package_name,
            "version": VERSION,
            "description": "Cross-platform desktop app for secure remote PC control and management.",
            "maintainer": "Azhar Zouhir <support@bytedz.com>",
            "homepage": "https://github.com/BYTEDz/PCLink",
            "license": "AGPL-3.0-or-later",
            "architecture": architecture,
        }

    def verify_python_environment(self):
        """Verify basic Python environment for build script execution."""
        if sys.version_info < (3, 8):
            print(
                f"[ERROR] Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}"
            )
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
            self.staging_dir
            / "usr"
            / "share"
            / "icons"
            / "hicolor"
            / "256x256"
            / "apps",
            self.staging_dir / "usr" / "share" / "doc" / "pclink",
            self.staging_dir / "usr" / "share" / "man" / "man1",
            self.staging_dir / "usr" / "lib" / "systemd" / "user",
            self.staging_dir / "etc" / "sudoers.d",
            self.staging_dir / "etc" / "udev" / "rules.d",
        ]

        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

    def create_wheel(self):
        """Create wheels for the package and its dependencies."""
        print("[WHEEL] Creating Python wheels for package and dependencies...")

        wheel_dir = self.build_dir / "wheels"
        wheel_dir.mkdir(parents=True, exist_ok=True)

        for old_wheel in wheel_dir.glob("*.whl"):
            old_wheel.unlink()

        # Use sys.executable to build wheels including dependencies for offline install
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "-w",
            str(wheel_dir),
            ".",
        ]
        try:
            subprocess.run(
                cmd, check=True, cwd=self.root_dir, capture_output=True, text=True
            )
            print("[OK] Wheel build completed")
        except subprocess.CalledProcessError as e:
            print("[ERROR] Wheel build failed:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise RuntimeError("Wheel creation failed")

        wheel_files = list(wheel_dir.glob("*.whl"))
        if not wheel_files:
            raise RuntimeError("No wheel files were created")

        print(f"[OK] Created {len(wheel_files)} wheels (package + dependencies)")
        return wheel_dir

    def install_application_files(self, existing_wheel_path=None):
        """Install application files and wheels to staging directory."""
        print("[FILES] Installing application files to staging...")

        if existing_wheel_path:
            wheel_dir = Path(existing_wheel_path).parent
        else:
            wheel_dir = self.create_wheel()

        pclink_dest_dir = self.staging_dir / "usr" / "lib" / "pclink"
        pclink_dest_dir.mkdir(parents=True, exist_ok=True)

        for whl in wheel_dir.glob("*.whl"):
            shutil.copy2(whl, pclink_dest_dir / whl.name)

        # --- Launcher Script ---
        launcher_content = """#!/bin/bash
# PCLink Launcher Script
INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
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
        launcher_path.write_text(launcher_content, encoding="utf-8")
        launcher_path.chmod(0o755)

        # --- Sudoers File (from template) ---
        sudoers_src = self.root_dir / "scripts/linux/pclink-sudoers"
        sudoers_dst = self.staging_dir / "etc" / "sudoers.d" / "pclink"
        if sudoers_src.exists():
            content = sudoers_src.read_text(encoding="utf-8")
            sudoers_dst.write_text(
                content.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8"
            )
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
            sudoers_dst.write_text(
                sudoers_content.replace("\r\n", "\n"), encoding="utf-8"
            )

        # --- Copy other resources ---
        resources = [
            ("scripts/linux/pclink-power-wrapper", "usr/bin/pclink-power-wrapper"),
            ("scripts/linux/test-power-permissions", "usr/bin/test-power-permissions"),
            (
                "xyz.bytedz.PCLink.desktop",
                "usr/share/applications/xyz.bytedz.PCLink.desktop",
            ),
            (
                "src/pclink/assets/icon.png",
                "usr/share/icons/hicolor/256x256/apps/xyz.bytedz.PCLink.png",
            ),
            (
                "scripts/linux/pclink.service.template",
                "usr/lib/systemd/user/pclink.service",
            ),
            ("scripts/linux/99-uinput.rules", "etc/udev/rules.d/99-uinput.rules"),
        ]

        for src_rel, dst_rel in resources:
            src = self.root_dir / src_rel
            dst = self.staging_dir / dst_rel
            if src.exists():
                shutil.copy2(src, dst)
                if "bin" in dst_rel:
                    dst.chmod(0o755)

                if dst_rel.endswith(
                    (
                        ".desktop",
                        ".service",
                        "pclink-power-wrapper",
                        "test-power-permissions",
                    )
                ):
                    content = dst.read_text(encoding="utf-8")
                    content = content.replace("\r\n", "\n").replace("\r", "\n")

                    if dst_rel.endswith("pclink.service"):
                        print("[FIX] Replacing placeholders in service file...")
                        content = content.replace("__EXEC_PATH__", "/usr/bin/pclink")
                        content = content.replace("__WORKING_DIR__", "%h")
                        content = content.replace("User=%i\n", "")
                        content = content.replace("Group=%i\n", "")
                        content = content.replace(
                            "ProtectHome=read-only", "ProtectHome=false"
                        )

                    dst.write_text(content, encoding="utf-8")

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
Azhar Zouhir <support@bytedz.com>
"""
        man_path = self.staging_dir / "usr" / "share" / "man" / "man1" / "pclink.1"
        man_path.write_text(man_content, encoding="utf-8")

        for doc_file in ["README.md", "LICENSE", "CHANGELOG.md"]:
            doc_src = self.root_dir / doc_file
            if doc_src.exists():
                shutil.copy2(
                    doc_src,
                    self.staging_dir / "usr" / "share" / "doc" / "pclink" / doc_file,
                )

    def create_scripts(self):
        """Create package installation/removal scripts."""
        print("[SCRIPTS] Creating final maintainer scripts (SAFE MODE)...")

        scripts_dir = self.build_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        postinst_content = """#!/bin/bash

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="/tmp/pclink_install.log"

log() {
    echo "$(date) - PCLink: $1" | tee -a "$LOG_FILE"
}

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
        if [ ! -d "$VENV_DIR" ]; then
            log "Creating virtual environment..."
            if command -v python3 >/dev/null; then
                python3 -m venv --system-site-packages "$VENV_DIR" >> "$LOG_FILE" 2>&1
                if [ $? -ne 0 ]; then
                    error "Failed to create virtual environment."
                fi
            else
                error "python3 not found, venv creation skipped."
            fi
        fi

        # Install Wheels offline
        if [ -f "$VENV_DIR/bin/pip" ]; then
            log "Installing wheels from $INSTALL_DIR..."
            if ! "$VENV_DIR/bin/pip" install --no-warn-script-location --no-index --find-links="$INSTALL_DIR" "$INSTALL_DIR"/pclink-*.whl >> "$LOG_FILE" 2>&1; then
                log "Offline wheel install failed, attempting fallback with online/system packages..."
                "$VENV_DIR/bin/pip" install --no-warn-script-location --find-links="$INSTALL_DIR" "$INSTALL_DIR"/pclink-*.whl >> "$LOG_FILE" 2>&1
            fi
        else
            error "pip missing in venv."
        fi

        # --- Permissions ---
        if [ "$(id -u)" -eq 0 ]; then
            if [ -f "/etc/sudoers.d/pclink" ]; then
                chmod 440 /etc/sudoers.d/pclink
            fi

            log "Setting up uinput permissions for Wayland..."
            if ! getent group input >/dev/null; then
                groupadd -r input || true
            fi

            if [ -f "/etc/udev/rules.d/99-uinput.rules" ]; then
                chmod 644 /etc/udev/rules.d/99-uinput.rules
                command -v udevadm >/dev/null 2>&1 && udevadm control --reload-rules && udevadm trigger --attr-match=subsystem=misc || true
            fi

            command -v modprobe >/dev/null 2>&1 && modprobe uinput || true
        fi

        log "Updating system caches..."
        command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
        command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true

        log "Configuration complete."
        ;;

    *)
        log "postinst called with unknown argument: $1"
        ;;
esac
exit 0
"""

        postinst_path = scripts_dir / "postinst"
        with open(postinst_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(postinst_content.strip())
        postinst_path.chmod(0o755)

        prerm_content = """#!/bin/bash

LOG_FILE="/tmp/pclink_install.log"
log() { echo "$(date) - PCLink: $1" | tee -a "$LOG_FILE"; }

echo "=== PCLink prerm: action='$1', old_version='$2', new_version='$3' ==="

case "$1" in
    remove|0)
        log "Stopping services for removal..."

        if command -v systemctl >/dev/null 2>&1; then
            for user_dir in /run/user/*/; do
                user_id=$(basename "$user_dir")
                if [ -n "$user_id" ] && [ "$user_id" != "*" ]; then
                    systemctl --user --machine="${user_id}@.host" stop pclink.service 2>/dev/null || true
                fi
            done
        fi

        pkill -f "/usr/lib/pclink" 2>/dev/null || true
        sleep 1
        ;;

    upgrade|deconfigure|1)
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
        with open(prerm_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(prerm_content.strip())
        prerm_path.chmod(0o755)

        postrm_content = """#!/bin/bash

INSTALL_DIR="/usr/lib/pclink"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="/tmp/pclink_install.log"
log() { echo "$(date) - PCLink: $1" | tee -a "$LOG_FILE"; }

echo "=== PCLink postrm: action='$1', old_version='$2' ==="
log "Starting postrm action=$1"

case "$1" in
    remove|0)
        log "Cleaning up installation..."

        if [ -d "$VENV_DIR" ]; then
            log "Removing virtual environment..."
            rm -rf "$VENV_DIR" 2>/dev/null || true
        fi

        if [ -d "$INSTALL_DIR" ]; then
            log "Removing wheel files..."
            find "$INSTALL_DIR" -name "*.whl" -type f -delete 2>/dev/null || true
            rmdir "$INSTALL_DIR" 2>/dev/null || true
        fi

        if command -v systemctl >/dev/null 2>&1; then
            systemctl --global disable pclink.service 2>/dev/null || true
            systemctl daemon-reload 2>/dev/null || true
        fi
        ;;

    purge)
        log "Purging configuration..."

        if [ -d "$INSTALL_DIR" ]; then
            log "Removing installation directory..."
            rm -rf "$INSTALL_DIR" 2>/dev/null || true
        fi
        rm -f "/etc/sudoers.d/pclink" 2>/dev/null || true

        if command -v systemctl >/dev/null 2>&1; then
            systemctl --global disable pclink.service 2>/dev/null || true
            systemctl daemon-reload 2>/dev/null || true
        fi
        ;;

    upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
        log "Package operation '$1' (no cleanup needed)"
        ;;

    *)
        log "postrm called with unknown argument: $1"
        ;;
esac

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
command -v mandb >/dev/null 2>&1 && mandb -q 2>/dev/null || true

log "postrm completed"
exit 0
"""

        postrm_path = scripts_dir / "postrm"
        with open(postrm_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(postrm_content.strip())
        postrm_path.chmod(0o755)

        return {
            "postinst": postinst_path,
            "prerm": prerm_path,
            "postrm": postrm_path,
        }

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

            print("\n--- Preparation Complete ---")
            print("To build packages, run NFPM from the project root:")
            print("  nfpm package -f nfpm.yaml")
            print("Or use GoReleaser.")

            return True

        except Exception as e:
            print(f"[ERROR] Build process failed: {e}")
            return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PCLink NFPM Package Pre-Builder")
    parser.add_argument(
        "--arch",
        default="amd64",
        help="Architecture for the package (e.g., amd64, arm64, armhf)",
    )
    args = parser.parse_args()

    try:
        builder = NFPMBuilder(architecture=args.arch)
        success = builder.build_all()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

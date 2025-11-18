#!/bin/bash

# --- PCLink Pre-Installation Script ---
# Handles safe installation/upgrade by detecting and cleaning existing installations
# Prevents conflicts from manual installs, broken packages, or orphaned files

set -e

PKG_NAME="pclink"
INSTALL_PATHS=(
    "/opt/pclink"
    "/usr/local/bin/pclink"
    "/usr/bin/pclink"
)

echo "================================================================"
echo "PCLink Pre-Installation Check"
echo "Detecting and handling existing installations..."
echo "================================================================"

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then 
        echo "ERROR: This script must be run as root or with sudo"
        exit 1
    fi
}

# Function to detect installation type
detect_installation() {
    local pkg_status=""
    local files_exist=false
    
    # Check dpkg database
    if dpkg -l | grep -q "^ii\s*${PKG_NAME}"; then
        pkg_status="installed"
    elif dpkg -l | grep -q "^[ihr][^i]\s*${PKG_NAME}"; then
        pkg_status="broken"
    elif dpkg -l | grep -q "${PKG_NAME}"; then
        pkg_status="partial"
    fi
    
    # Check for installed files
    for path in "${INSTALL_PATHS[@]}"; do
        if [ -e "$path" ]; then
            files_exist=true
            break
        fi
    done
    
    echo "$pkg_status:$files_exist"
}

# Function to handle clean installation
handle_clean_install() {
    echo ""
    echo "✓ No existing installation detected."
    echo "  System is ready for fresh installation."
    echo ""
}

# Function to handle upgrade
handle_upgrade() {
    echo ""
    echo "→ Existing PCLink installation detected (properly registered)."
    echo "  Preparing for upgrade..."
    echo ""
    
    # Stop any running instances
    echo "1. Stopping running PCLink instances..."
    pkill -f "pclink" 2>/dev/null || true
    systemctl stop pclink 2>/dev/null || true
    sleep 2
    
    # Remove old package (dpkg will handle this during upgrade, but we ensure it)
    echo "2. Removing old package version..."
    dpkg --remove ${PKG_NAME} 2>/dev/null || true
    
    echo "   Ready for upgrade."
    echo ""
}

# Function to handle broken package
handle_broken_package() {
    echo ""
    echo "⚠ Broken PCLink package detected in dpkg database!"
    echo "  This needs to be cleaned before installation."
    echo ""
    
    read -p "Run force-purge script to fix? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if [ -f "./force-purge-pclink.sh" ]; then
            echo "Running force-purge script..."
            bash ./force-purge-pclink.sh
        else
            echo "ERROR: force-purge-pclink.sh not found in current directory."
            echo "Please download it from the PCLink repository and run it manually."
            exit 1
        fi
    else
        echo "Installation cancelled. Please fix the broken package first."
        exit 1
    fi
}

# Function to handle orphaned files
handle_orphaned_files() {
    echo ""
    echo "⚠ PCLink files detected but not registered in package manager!"
    echo "  This suggests a manual installation or incomplete removal."
    echo ""
    
    echo "Detected files/directories:"
    for path in "${INSTALL_PATHS[@]}"; do
        if [ -e "$path" ]; then
            echo "  - $path"
        fi
    done
    echo ""
    
    read -p "Remove these files to allow clean installation? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Cleaning orphaned files..."
        
        # Stop any running instances
        pkill -f "pclink" 2>/dev/null || true
        systemctl stop pclink 2>/dev/null || true
        sleep 2
        
        # Remove files
        rm -rf /opt/pclink 2>/dev/null || true
        rm -f /usr/local/bin/pclink 2>/dev/null || true
        rm -f /usr/bin/pclink 2>/dev/null || true
        rm -f /usr/share/applications/pclink.desktop 2>/dev/null || true
        rm -f /usr/share/applications/xyz.bytedz.PCLink.desktop 2>/dev/null || true
        rm -rf /usr/share/pclink 2>/dev/null || true
        rm -f /usr/share/icons/hicolor/*/apps/pclink.* 2>/dev/null || true
        rm -f /etc/systemd/system/pclink.service 2>/dev/null || true
        rm -f /usr/lib/systemd/user/pclink.service 2>/dev/null || true
        systemctl daemon-reload 2>/dev/null || true
        
        echo "✓ Orphaned files removed."
        echo ""
    else
        echo ""
        echo "WARNING: Installation may fail due to file conflicts."
        echo "Continue anyway? (y/n): "
        read -p "" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Installation cancelled."
            exit 1
        fi
    fi
}

# Function to handle mixed state (broken + orphaned)
handle_mixed_state() {
    echo ""
    echo "⚠ Complex situation detected:"
    echo "  - Broken package in dpkg database"
    echo "  - Orphaned files on filesystem"
    echo ""
    echo "Running comprehensive cleanup..."
    echo ""
    
    if [ -f "./force-purge-pclink.sh" ]; then
        bash ./force-purge-pclink.sh
    else
        echo "ERROR: force-purge-pclink.sh not found."
        echo "Attempting manual cleanup..."
        
        # Manual cleanup
        dpkg --remove --force-all ${PKG_NAME} 2>/dev/null || true
        dpkg --purge --force-all ${PKG_NAME} 2>/dev/null || true
        rm -f /var/lib/dpkg/info/${PKG_NAME}.* 2>/dev/null || true
        sed -i "/^Package: ${PKG_NAME}$/,/^$/d" /var/lib/dpkg/status 2>/dev/null || true
        
        # Remove files
        rm -rf /opt/pclink 2>/dev/null || true
        rm -f /usr/local/bin/pclink 2>/dev/null || true
        rm -f /usr/bin/pclink 2>/dev/null || true
        
        apt-get update 2>/dev/null || true
        apt-get install -f -y 2>/dev/null || true
    fi
    
    echo "✓ Cleanup completed."
    echo ""
}

# Function to install package
install_package() {
    local deb_file="$1"
    
    echo "================================================================"
    echo "Installing PCLink..."
    echo "================================================================"
    echo ""
    
    # Install the package
    dpkg -i "$deb_file"
    
    # Fix any dependency issues
    apt-get install -f -y
    
    echo ""
    echo "================================================================"
    echo "✓ PCLink installed successfully!"
    echo "================================================================"
}

# Main execution
main() {
    check_root
    
    # Detect current state
    local state=$(detect_installation)
    local pkg_status=$(echo "$state" | cut -d: -f1)
    local files_exist=$(echo "$state" | cut -d: -f2)
    
    # Handle different scenarios
    if [ "$pkg_status" = "installed" ]; then
        handle_upgrade
    elif [ "$pkg_status" = "broken" ] && [ "$files_exist" = "true" ]; then
        handle_mixed_state
    elif [ "$pkg_status" = "broken" ]; then
        handle_broken_package
    elif [ "$files_exist" = "true" ]; then
        handle_orphaned_files
    else
        handle_clean_install
    fi
    
    # Check if .deb file provided
    if [ -n "$1" ]; then
        if [ -f "$1" ]; then
            install_package "$1"
        else
            echo "ERROR: File not found: $1"
            exit 1
        fi
    else
        echo "================================================================"
        echo "System is ready for PCLink installation."
        echo ""
        echo "To install, run:"
        echo "  sudo bash pre-install-pclink.sh pclink_VERSION_amd64.deb"
        echo ""
        echo "Or install manually:"
        echo "  sudo dpkg -i pclink_VERSION_amd64.deb"
        echo "  sudo apt-get install -f"
        echo "================================================================"
    fi
}

# Run main function with optional .deb file argument
main "$@"

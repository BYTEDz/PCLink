#!/bin/bash

# --- PCLink Broken Package Rescue Script (v2.0.0 - v2.5.0) ---
# This script forcibly removes broken PCLink installations and fixes package manager issues
# Handles: broken maintainer scripts, corrupted dpkg state, "needs to be reinstalled" errors

set -e  # Exit on error (disabled for specific commands that may fail)

PKG_NAME="pclink"
DPKG_INFO_DIR="/var/lib/dpkg/info"
DPKG_STATUS="/var/lib/dpkg/status"

echo "================================================================"
echo "PCLink Package Manager Rescue Script"
echo "Fixes broken installations and package manager corruption"
echo "================================================================"

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then 
        echo "ERROR: This script must be run as root or with sudo"
        exit 1
    fi
}

# Function to backup dpkg status
backup_dpkg_status() {
    echo "Creating backup of dpkg status..."
    cp "$DPKG_STATUS" "${DPKG_STATUS}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
}

# Function to fix dpkg lock issues
fix_dpkg_locks() {
    echo "1. Checking and fixing dpkg lock issues..."
    
    # Remove lock files if they exist
    rm -f /var/lib/dpkg/lock-frontend 2>/dev/null || true
    rm -f /var/lib/dpkg/lock 2>/dev/null || true
    rm -f /var/cache/apt/archives/lock 2>/dev/null || true
    rm -f /var/lib/apt/lists/lock 2>/dev/null || true
    
    echo "   Lock files cleared."
}

# Function to fix broken dpkg state
fix_dpkg_state() {
    echo "2. Recovering dpkg state..."
    
    # Try to configure any pending packages
    dpkg --configure -a 2>/dev/null || true
    
    # Fix broken dependencies
    apt-get install -f -y 2>/dev/null || true
    
    echo "   DPKG state recovered."
}

# Function to remove package from dpkg status manually
remove_from_dpkg_status() {
    echo "3. Removing ${PKG_NAME} from dpkg status database..."
    
    backup_dpkg_status
    
    # Remove package entry from status file
    sed -i "/^Package: ${PKG_NAME}$/,/^$/d" "$DPKG_STATUS" 2>/dev/null || true
    
    echo "   Package removed from dpkg database."
}

# Function to remove all package files
remove_package_files() {
    echo "4. Removing all ${PKG_NAME} maintainer scripts and metadata..."
    
    # Remove all dpkg info files for the package
    rm -f ${DPKG_INFO_DIR}/${PKG_NAME}.* 2>/dev/null || true
    
    # Remove list files
    rm -f /var/lib/dpkg/info/${PKG_NAME}:*.* 2>/dev/null || true
    
    echo "   Maintainer scripts removed."
}

# Function to stop running instances
stop_running_instances() {
    echo "5. Stopping any running PCLink instances..."
    
    # Kill running processes
    pkill -f "pclink" 2>/dev/null || true
    pkill -9 -f "pclink" 2>/dev/null || true
    
    # Stop systemd services
    systemctl stop pclink 2>/dev/null || true
    systemctl disable pclink 2>/dev/null || true
    
    # Wait for processes to terminate
    sleep 2
    
    echo "   Running instances stopped."
}

# Function to clean installed files
clean_installed_files() {
    echo "6. Cleaning installed PCLink files (including manual installations)..."
    
    # Common installation paths
    rm -rf /opt/pclink 2>/dev/null || true
    rm -rf /usr/local/bin/pclink 2>/dev/null || true
    rm -rf /usr/bin/pclink 2>/dev/null || true
    rm -f /usr/share/applications/pclink.desktop 2>/dev/null || true
    rm -f /usr/share/applications/xyz.bytedz.PCLink.desktop 2>/dev/null || true
    rm -rf /usr/share/pclink 2>/dev/null || true
    rm -f /usr/share/icons/hicolor/*/apps/pclink.* 2>/dev/null || true
    
    # Systemd service files
    rm -f /etc/systemd/system/pclink.service 2>/dev/null || true
    rm -f /usr/lib/systemd/user/pclink.service 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true
    
    # User data directories (optional - uncomment if needed)
    # rm -rf ~/.config/pclink 2>/dev/null || true
    # rm -rf ~/.local/share/pclink 2>/dev/null || true
    
    echo "   Installed files cleaned."
}

# Function to force remove package
force_remove_package() {
    echo "7. Force removing package with all dpkg options..."
    
    # Check if package exists in dpkg database
    if dpkg -l | grep -q "${PKG_NAME}"; then
        echo "   Package found in dpkg database, attempting removal..."
        
        # Try multiple removal strategies
        dpkg --remove --force-remove-reinstreq --force-depends ${PKG_NAME} 2>/dev/null || true
        dpkg --purge --force-remove-reinstreq --force-depends ${PKG_NAME} 2>/dev/null || true
        dpkg --purge --force-all ${PKG_NAME} 2>/dev/null || true
    else
        echo "   Package not in dpkg database (manual installation detected)."
    fi
    
    echo "   Force removal completed."
}

# Function to clean package cache
clean_package_cache() {
    echo "8. Cleaning package cache and archives..."
    
    # Remove any cached .deb files
    rm -f /var/cache/apt/archives/${PKG_NAME}*.deb 2>/dev/null || true
    
    apt-get clean 2>/dev/null || true
    apt-get autoclean 2>/dev/null || true
    
    echo "   Cache cleaned."
}

# Function to fix apt database
fix_apt_database() {
    echo "9. Fixing APT database..."
    
    # Update package lists
    apt-get update 2>/dev/null || true
    
    # Fix broken packages
    apt-get install -f -y 2>/dev/null || true
    
    # Remove unused packages
    apt-get autoremove -y 2>/dev/null || true
    
    echo "   APT database fixed."
}

# Function to verify cleanup
verify_cleanup() {
    echo "10. Verifying cleanup..."
    
    local issues_found=false
    
    # Check dpkg database
    if dpkg -l | grep -q "^[ihr]i\s*${PKG_NAME}"; then
        echo "   WARNING: Package still in dpkg database. Performing deep cleanup..."
        remove_from_dpkg_status
        remove_package_files
        issues_found=true
    fi
    
    # Check for remaining files
    if [ -e "/opt/pclink" ] || [ -e "/usr/bin/pclink" ] || [ -e "/usr/local/bin/pclink" ]; then
        echo "   WARNING: Some PCLink files still exist. Removing..."
        clean_installed_files
        issues_found=true
    fi
    
    if [ "$issues_found" = false ]; then
        echo "   ✓ SUCCESS: Complete cleanup verified."
    else
        echo "   ✓ Deep cleanup completed."
    fi
}

# Main execution
main() {
    check_root
    
    echo ""
    echo "Starting comprehensive cleanup for: ${PKG_NAME}"
    echo ""
    
    # Execute all cleanup steps
    fix_dpkg_locks
    fix_dpkg_state
    remove_package_files
    force_remove_package
    remove_from_dpkg_status
    clean_installed_files
    clean_package_cache
    fix_apt_database
    verify_cleanup
    
    echo ""
    echo "================================================================"
    echo "Rescue complete! Package manager should now be functional."
    echo ""
    echo "You can now safely install PCLink with:"
    echo "  sudo dpkg -i pclink_*.deb"
    echo "  sudo apt-get install -f"
    echo "================================================================"
}

# Run main function
main
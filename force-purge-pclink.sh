#!/bin/bash

# --- PCLink Broken Package Rescue Script (v2.0.0 - v2.3.0) ---
# This script is required to forcibly remove previous versions of PCLink
# whose uninstallation scripts crash on some systems.

PKG_NAME="pclink"

echo "================================================================"
echo "Starting rescue process for broken package: $PKG_NAME"
echo "Fixes uninstallation for versions 2.0.0, 2.1.0, 2.2.0, and 2.3.0."
echo "================================================================"

# Check if the package is even installed before proceeding
if ! dpkg -l | grep -q "^[ihr]i\s*pclink"; then
    echo "The '${PKG_NAME}' package does not appear to be installed or is already removed."
    echo "Proceeding to system cleanup."
else
    # 1. Recover DPKG state
    echo "1. Attempting to recover dpkg state..."
    sudo dpkg --configure -a

    # 2. Manually clear the broken maintainer scripts
    echo "2. Removing broken maintainer scripts from /var/lib/dpkg/info to prevent crash..."
    # The DPKG database stores copies of the scripts run on install/remove
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.prerm
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.postinst
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.postrm
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.preinst
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.postinst-old
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.prerm-old
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.postrm-old
    sudo rm -f /var/lib/dpkg/info/${PKG_NAME}.triggers

    # 3. Force the removal (purge) of the package
    echo "3. Forcing complete removal (purge) of the package..."
    # --force-remove-reinstreq is necessary for packages stuck in a bad state
    # This command uses the clean DPKG status to finalize the removal
    sudo dpkg --force-remove-reinstreq --purge ${PKG_NAME}
fi

# 4. Final system cleanup
echo "4. Performing final system cleanup..."
sudo apt autoremove
sudo apt clean
sudo apt update

echo "================================================================"
echo "Rescue complete. The broken package '${PKG_NAME}' has been forcibly removed."
echo "You can now proceed to install the new, fixed version."
echo "================================================================"
#!/bin/bash
# PCLink Smart Installer & Updater
# One-liner (interactive): bash <(curl -fsSL https://raw.githubusercontent.com/BYTEDz/PCLink/main/install.sh)
# One-liner (non-interactive): bash <(curl -fsSL https://raw.githubusercontent.com/BYTEDz/PCLink/main/install.sh) -y

set -euo pipefail

REPO="BYTEDz/PCLink"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"
TMP_DIR=""
UPDATE_MODE=false
ASSUME_YES=false

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[ERROR]${NC} $1" >&2; cleanup; exit 1; }

ask() {
    local prompt="$1"
    local default="${2:-}"
    local response
    if [[ "$ASSUME_YES" == "true" ]]; then
        return 0
    fi
    if [ -t 0 ] || [ -c /dev/tty ]; then
        read -rp "$(echo -e "${YELLOW}${prompt}${NC} ")" response < /dev/tty
    else
        response="$default"
    fi
    if [[ -z "$response" ]]; then response="$default"; fi
    [[ "${response,,}" =~ ^(y|yes)$ ]]
}

cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

for arg in "$@"; do
    case $arg in
        --update|-u) UPDATE_MODE=true ;;
        --yes|-y)    ASSUME_YES=true ;;
        --help|-h)
            echo "Usage: $0 [--update] [--yes]"
            echo "Options:"
            echo "  --update, -u    Force update even if version matches"
            echo "  --yes, -y       Assume yes to all prompts"
            exit 0
            ;;
    esac
done

detect_arch() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64)        echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        armv7l)        echo "armhf" ;;
        *) fail "Unsupported architecture: $arch" ;;
    esac
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        # Using a subshell to avoid polluting the installer's environment
        ( . /etc/os-release && echo "$ID" )
    elif command -v lsb_release &>/dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        fail "Cannot detect Linux distribution"
    fi
}

detect_pkg_format() {
    local os_identifiers=""
    
    # Safely extract ID and ID_LIKE from os-release to determine the OS "family"
    if [ -f /etc/os-release ]; then
        os_identifiers=$(grep -E '^(ID|ID_LIKE)=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'" | tr '\n' ' ' | tr '[:upper:]' '[:lower:]' || true)
    fi

    # Smartly map the underlying family to the package type
    if [[ "$os_identifiers" == *"debian"* || "$os_identifiers" == *"ubuntu"* ]]; then
        echo "deb"
    elif [[ "$os_identifiers" == *"fedora"* || "$os_identifiers" == *"rhel"* || "$os_identifiers" == *"centos"* || "$os_identifiers" == *"suse"* || "$os_identifiers" == *"alma"* || "$os_identifiers" == *"rocky"* || "$os_identifiers" == *"amzn"* ]]; then
        echo "rpm"
    elif [[ "$os_identifiers" == *"arch"* ]]; then
        echo "archlinux"
    else
        # Smart fallback: look for high-level package managers first (which are harder to false-positive)
        if command -v apt-get &>/dev/null; then echo "deb"
        elif command -v dnf &>/dev/null || command -v yum &>/dev/null || command -v zypper &>/dev/null; then echo "rpm"
        elif command -v pacman &>/dev/null; then echo "archlinux"
        elif command -v dpkg &>/dev/null; then echo "deb"
        elif command -v rpm &>/dev/null; then echo "rpm"
        else
            fail "No supported package manager found (apt/dnf/pacman)."
        fi
    fi
}

get_pkg_extension() {
    case "$1" in
        deb)       echo "\.deb" ;;
        rpm)       echo "\.rpm" ;;
        archlinux) echo "\.pkg\.tar\.zst" ;;
    esac
}

get_current_version() {
    if command -v pclink &>/dev/null; then
        pclink --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' || echo "installed-unknown"
    else
        echo "none"
    fi
}

version_gt() { test "$(printf '%s\n' "$@" | sort -V | sed -n '1p')" != "$1"; }

fetch_release_info() {
    local json
    if command -v curl &>/dev/null; then
        json=$(curl -fsSL "$API_URL" 2>/dev/null) || fail "Failed to fetch release info from GitHub"
    elif command -v wget &>/dev/null; then
        json=$(wget -qO- "$API_URL" 2>/dev/null) || fail "Failed to fetch release info from GitHub"
    else
        fail "Neither curl nor wget found."
    fi
    
    if [[ "$json" != *'"tag_name"'* ]]; then
        fail "GitHub API response invalid or rate-limited.\nResponse: ${json:0:200}..."
    fi
    echo "$json"
}

find_asset_url() {
    local json="$1" arch="$2" ext="$3"
    local url

    local arch_patterns=("$arch")
    [[ "$arch" == "amd64" ]] && arch_patterns+=("x86_64")
    [[ "$arch" == "arm64" ]] && arch_patterns+=("aarch64")
    [[ "$ext" == "\.pkg\.tar\.zst" ]] && arch_patterns+=("any")

    for pattern in "${arch_patterns[@]}"; do
        url=$(echo "$json" | grep -oP '"browser_download_url"\s*:\s*"\K[^"]*?'"${pattern}"'[^"]*?'"${ext}"'(?=")' | sed -n '1p' || true)
        if [[ -n "$url" ]]; then
            echo "$url"
            return 0
        fi
    done
    return 1
}

download_file() {
    local url="$1" dest="$2"
    info "Downloading: $(basename "$dest")"
    if command -v curl &>/dev/null; then
        curl -fSL --progress-bar -o "$dest" "$url"
    elif command -v wget &>/dev/null; then
        wget --show-progress -qO "$dest" "$url"
    fi
}

install_package() {
    local pkg="$1" format="$2"
    case "$format" in
        deb)
            info "Installing via apt..."
            sudo dpkg -i "$pkg" 2>/dev/null || true
            sudo apt-get install -f -y
            ;;
        rpm)
            info "Installing via dnf/yum..."
            if command -v dnf &>/dev/null; then sudo dnf install -y "$pkg"
            elif command -v yum &>/dev/null; then sudo yum install -y "$pkg"
            else sudo rpm -Uvh "$pkg"
            fi
            ;;
        archlinux)
            info "Installing via pacman..."
            sudo pacman -U --noconfirm "$pkg"
            ;;
    esac
}

fallback_python_install() {
    info "Falling back to Python installation..."
    if command -v pipx &>/dev/null; then
        pipx install pclink || fail "Pipx installation failed."
    else
        python3 -m pip install --user --upgrade pclink --break-system-packages 2>/dev/null || \
        python3 -m pip install --user --upgrade pclink || fail "Pip installation failed."
    fi
    ok "Installed successfully via Python environment."
    exit 0
}

main() {
    echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║          PCLink Smart Installer          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}\n"

    local current_v latest_v arch distro pkg_format ext
    current_v=$(get_current_version)
    arch=$(detect_arch)
    distro=$(detect_distro)
    
    pkg_format=$(detect_pkg_format) 
    ext=$(get_pkg_extension "$pkg_format")

    info "System: ${BOLD}${distro}${NC} (${arch}) → ${pkg_format}"
    
    if [[ "$current_v" != "none" ]]; then
        info "Currently installed: ${BOLD}${current_v}${NC}"
    fi

    info "Fetching latest release information..."
    local release_json
    release_json=$(fetch_release_info)
    
    latest_v=$(echo "$release_json" | grep -oP '"tag_name"\s*:\s*"v?\K[^"]+' | sed -n '1p' || true)
    
    ok "Latest version: ${BOLD}${latest_v}${NC}"

    if [[ "$current_v" != "none" && "$UPDATE_MODE" == "false" ]]; then
        if [[ "$current_v" == "$latest_v" ]]; then
            ok "PCLink is already up to date."
            if ! ask "Reinstall anyway? [y/N]" "n"; then exit 0; fi
        elif version_gt "$latest_v" "$current_v"; then
            info "New version available! ${current_v} -> ${latest_v}"
        else
            warn "Installed version (${current_v}) is newer than latest release (${latest_v})."
            if ! ask "Downgrade anyway? [y/N]" "n"; then exit 0; fi
        fi
    fi

    local asset_url
    asset_url=$(find_asset_url "$release_json" "$arch" "$ext") || {
        warn "No matching native package found for ${arch}."
        fallback_python_install
    }

    ok "Target package: $(basename "$asset_url")"

    echo ""
    if ! ask "This will install PCLink ${latest_v} system-wide (requires sudo). Continue? [Y/n]" "y"; then
        info "Installation cancelled."
        exit 0
    fi

    TMP_DIR=$(mktemp -d)
    local pkg_file="${TMP_DIR}/$(basename "$asset_url")"
    download_file "$asset_url" "$pkg_file"
    
    echo ""
    info "Preparing for system-wide installation..."
    install_package "$pkg_file" "$pkg_format"

    echo -e "\n${GREEN}${BOLD}✓ PCLink ${latest_v} installed successfully!${NC}"
    echo "  - Run:     pclink"
    echo "  - Service: systemctl --user enable --now pclink"
    echo ""
}

main "$@"
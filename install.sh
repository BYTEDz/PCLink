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

# Setup colors safely (only if outputting to a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

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

    if [ -t 0 ] && [ -c /dev/tty ]; then
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

# Parse CLI Arguments
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

check_dependencies() {
    if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
        fail "Neither 'curl' nor 'wget' was found. Please install one to continue."
    fi
}

get_sudo_cmd() {
    if [ "$EUID" -ne 0 ]; then
        if command -v sudo &>/dev/null; then
            echo "sudo"
        else
            fail "Root privileges required but 'sudo' is not installed."
        fi
    else
        echo ""
    fi
}

detect_arch() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64)            echo "amd64" ;;
        aarch64|arm64)     echo "arm64" ;;
        armv7l|armv6l)     echo "armhf" ;;
        i386|i686)         echo "i386" ;;
        *)                 fail "Unsupported architecture: $arch" ;;
    esac
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        ( . /etc/os-release && echo "${ID:-linux}" )
    elif command -v lsb_release &>/dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        echo "linux"
    fi
}

detect_pkg_format() {
    local os_identifiers=""

    if [ -f /etc/os-release ]; then
        # Safely extract flat string of ID and ID_LIKE, stripping quotes
        os_identifiers=$(grep -E '^(ID|ID_LIKE)=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'" | tr '\n' ' ' | tr '[:upper:]' '[:lower:]' || true)
    fi

    # Smart fallback & family detection
    if [[ "$os_identifiers" == *"debian"* || "$os_identifiers" == *"ubuntu"* ]]; then
        echo "deb"
    elif [[ "$os_identifiers" == *"fedora"* || "$os_identifiers" == *"rhel"* || "$os_identifiers" == *"centos"* || "$os_identifiers" == *"suse"* || "$os_identifiers" == *"alma"* || "$os_identifiers" == *"rocky"* || "$os_identifiers" == *"amzn"* ]]; then
        echo "rpm"
    elif [[ "$os_identifiers" == *"arch"* ]]; then
        echo "archlinux"
    else
        # Direct Binary Fallback
        if command -v apt-get &>/dev/null || command -v dpkg &>/dev/null; then echo "deb"
        elif command -v dnf &>/dev/null || command -v yum &>/dev/null || command -v zypper &>/dev/null || command -v rpm &>/dev/null; then echo "rpm"
        elif command -v pacman &>/dev/null; then echo "archlinux"
        else echo "unknown"
        fi
    fi
}

get_pkg_extension() {
    case "$1" in
        deb)       echo "\.deb" ;;
        rpm)       echo "\.rpm" ;;
        archlinux) echo "\.pkg\.tar\.[a-z]+" ;; # Matches .zst, .xz, etc.
        *)         echo "none" ;;
    esac
}

get_current_version() {
    if command -v pclink &>/dev/null; then
        pclink --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || echo "installed-unknown"
    else
        echo "none"
    fi
}

version_gt() { test "$(printf '%s\n' "$@" | sort -V | sed -n '1p')" != "$1"; }

fetch_release_info() {
    local json
    if command -v curl &>/dev/null; then
        json=$(curl -fsSL --connect-timeout 10 "$API_URL" 2>/dev/null) || fail "Failed to fetch release info from GitHub"
    else
        json=$(wget -q --timeout=10 -O- "$API_URL" 2>/dev/null) || fail "Failed to fetch release info from GitHub"
    fi

    if [[ "$json" != *'"tag_name"'* ]]; then
        fail "GitHub API response invalid or rate-limited.\nResponse: ${json:0:200}..."
    fi
    echo "$json"
}

find_asset_url() {
    local json="$1" arch="$2" ext="$3"

    # Map architectures for the grep pattern
    local arch_pattern="(${arch}"
    [[ "$arch" == "amd64" ]] && arch_pattern+="|x86_64"
    [[ "$arch" == "arm64" ]] && arch_pattern+="|aarch64"
    arch_pattern+=")"

    [[ "$ext" == "\.pkg\.tar\.[a-z]+" ]] && arch_pattern="(any|${arch_pattern})"

    # Extract all download URLs and filter robustly without relying on PCRE (\K)
    echo "$json" | grep -Eo '"browser_download_url":\s*"[^"]+"' | cut -d'"' -f4 | grep -E "${arch_pattern}.*${ext}$" | head -n 1
}

download_file() {
    local url="$1" dest="$2"
    info "Downloading: $(basename "$dest")"
    if command -v curl &>/dev/null; then
        curl -fSL --connect-timeout 15 --progress-bar -o "$dest" "$url"
    else
        wget --show-progress -q --timeout=15 -O "$dest" "$url"
    fi
}

install_package() {
    local pkg="$1" format="$2"
    local sudo_cmd
    sudo_cmd=$(get_sudo_cmd)

    case "$format" in
        deb)
            info "Installing via apt..."
            # apt correctly handles local deb dependencies natively
            $sudo_cmd apt-get install -y "$pkg"
            ;;
        rpm)
            info "Installing via dnf/yum/zypper..."
            if command -v dnf &>/dev/null; then $sudo_cmd dnf install -y "$pkg"
            elif command -v zypper &>/dev/null; then $sudo_cmd zypper --non-interactive install "$pkg"
            elif command -v yum &>/dev/null; then $sudo_cmd yum install -y "$pkg"
            else $sudo_cmd rpm -Uvh "$pkg"
            fi
            ;;
        archlinux)
            info "Installing via pacman..."
            $sudo_cmd pacman -U --noconfirm "$pkg"
            ;;
        *)
            fail "Unsupported package format."
            ;;
    esac
}

fallback_python_install() {
    info "Falling back to Python installation..."
    if command -v pipx &>/dev/null; then
        info "Using pipx (recommended for isolated environments)..."
        pipx install pclink || fail "pipx installation failed."
    elif command -v python3 &>/dev/null && command -v pip &>/dev/null; then
        info "Using pip..."
        # Safely attempts user install, falls back to overriding system packages if user insists on pip vs pipx
        python3 -m pip install --user --upgrade pclink 2>/dev/null || \
        python3 -m pip install --user --upgrade pclink --break-system-packages 2>/dev/null || \
        fail "Pip installation failed. Consider installing 'pipx' instead."
    else
        fail "Python environment (pipx/pip) not found. Cannot fallback."
    fi
    ok "Installed successfully via Python environment."
    exit 0
}

main() {
    echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║              PCLink Installer            ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}\n"

    check_dependencies

    local current_v latest_v arch distro pkg_format ext
    current_v=$(get_current_version)
    arch=$(detect_arch)
    distro=$(detect_distro)

    pkg_format=$(detect_pkg_format)
    ext=$(get_pkg_extension "$pkg_format")

    if [[ "$pkg_format" == "unknown" ]]; then
        warn "System: ${BOLD}${distro}${NC} (${arch}) → Package manager not supported natively."
        fallback_python_install
    else
        info "System: ${BOLD}${distro}${NC} (${arch}) → ${pkg_format}"
    fi

    if [[ "$current_v" != "none" ]]; then
        info "Currently installed: ${BOLD}${current_v}${NC}"
    fi

    info "Fetching latest release information..."
    local release_json
    release_json=$(fetch_release_info)

    # Robust POSIX regex extraction of version
    latest_v=$(echo "$release_json" | grep -Eo '"tag_name":\s*"v?[^"]+"' | head -n 1 | sed -E 's/.*"v?([^"]+)".*/\1/' || true)

    if [[ -z "$latest_v" ]]; then
        fail "Could not determine the latest version from GitHub API."
    fi

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
    asset_url=$(find_asset_url "$release_json" "$arch" "$ext") || true

    if [[ -z "$asset_url" ]]; then
        warn "No matching native package found for ${arch} on ${pkg_format}."
        fallback_python_install
    fi

    ok "Target package: $(basename "$asset_url")"

    echo ""
    if ! ask "This will install PCLink ${latest_v} system-wide. Continue? [Y/n]" "y"; then
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

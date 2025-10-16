<div align="center">

![PCLink Banner](docs/assets/banner.svg)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11%20%7C%20Linux%20Mint%2022.1-lightgrey)](https://github.com/BYTEDz/PCLink)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/BYTEDz/PCLink?include_prereleases)](https://github.com/BYTEDz/PCLink/releases)
[![Play Store](https://img.shields.io/badge/Android-Play%20Store-brightgreen?logo=google-play)](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)

</div>

---

<div align="center">

**PCLink** is a modern, **web-first** application for **secure remote PC control** from mobile devices.  
It features a **FastAPI server**, **responsive web interface**, and **lightweight system tray**.

</div>

**Created by [Azhar Zouhir](https://github.com/AzharZouhir) / BYTEDz**

> 📱 **Need the mobile app?** Get it at [Google Play Store](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)

---

## 🚀 Features

### 🌐 Web-First Interface
- **Modern Web UI**: Responsive, dark-themed control panel
- **Real-time Updates**: WebSocket-powered live data
- **QR Code Pairing**: Visual device pairing with actual QR codes
- **Cross-Platform**: Works on any device with a browser
- **No Dependencies**: Zero Qt/GUI library requirements

### 🔧 Core Functionality
- **Remote Control**: File browser, process manager, terminal access
- **Media & Input**: Media playback, keyboard/mouse input, clipboard sync
- **System Actions**: Shutdown, restart, volume control, system info
- **Screen Capture**: Remote screenshots
- **Device Management**: Pairing, approval, and revocation

### 🔒 Security & Authentication
- **Web UI Authentication**: Password-protected interface with sessions
- **HTTPS Only**: Auto-generated self-signed certificates
- **API Key Authentication**: Secure device access
- **Session Management**: 24-hour sessions with automatic cleanup
- **Secure Pairing**: QR code-based device authentication

---

## 💻 System Requirements

### ✅ Tested Platforms
- **Windows 10/11** - Full support with system tray and power management
- **Linux Mint 22.1 Xia** - Complete integration with AppIndicator tray and systemd

### 🔧 Requirements
- **Python 3.8+** (automatically handled in packaged installations)
- **Network access** for mobile device communication
- **Administrator privileges** for power management features (optional)

---

## 📱 Mobile App Required

The server requires the companion mobile app:

- 🌐 [Official Website](https://bytedz.xyz/products/pclink/)
- 📱 [Google Play](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)  
- 🍎 iOS: Coming soon

---

## 🛠️ Installation & Setup

### 🚀 Recommended: Native Packages

#### Windows 10/11
1. Download the latest `.exe` installer from [Releases](https://github.com/BYTEDz/PCLink/releases)
2. Run the installer with administrator privileges
3. PCLink will be available in Start Menu and system tray

#### Linux (Ubuntu/Debian)
1. Download the latest `.deb` package from [Releases](https://github.com/BYTEDz/PCLink/releases)
2. Install: `sudo dpkg -i pclink_*.deb`
3. Fix dependencies if needed: `sudo apt-get install -f`
4. Start: `pclink` or find in applications menu

### 🐍 Python Installation

#### System Dependencies (Linux Only)
```bash
# Install all required system dependencies first
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-appindicator3-0.1 gir1.2-gtk-3.0 python3-tk python3-dev python3.12-venv gcc build-essential
```

#### Install PCLink
```bash
# Option 1: Install from requirements
pip install -r requirements.txt

# Option 2: Install directly from GitHub
pip install git+https://github.com/BYTEDz/PCLink.git
```

### 🎛️ Usage

```bash
# Start PCLink (opens web interface automatically)
pclink

# Background/startup mode (system tray only)
pclink --startup

# Don't auto-open browser
pclink --no-browser

# Test power command permissions (Linux)
test-power-permissions
```

### 🔧 First Time Setup
1. **Set Web UI Password**: Access https://localhost:38080/ui/ and create a password
2. **Pair Mobile Device**: Scan the QR code with the PCLink mobile app
3. **Configure Startup**: Enable "Start with system" in web UI settings

---

## 👨‍💻 Development

### 🛠️ Development Setup

```bash
# Linux: Install system dependencies first
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-tk python3-dev python3.12-venv gcc build-essential libgirepository1.0-dev libcairo2-dev pkg-config

# Clone repository
git clone https://github.com/BYTEDz/PCLink.git
cd PCLink

# Create virtual environment
python3 -m venv pclink-env
source pclink-env/bin/activate  # Linux/macOS
# or: pclink-env\Scripts\activate  # Windows

# Install runtime dependencies
pip install -r requirements.txt

# Install development dependencies (includes PyInstaller for building)
pip install -r requirements-dev.txt

# Install PCLink in development mode
pip install -e .

# Install pre-commit hooks
pre-commit install

# Run PCLink
python -m pclink

# Run tests
pytest
```

### 📦 Building Packages

#### Linux .deb Packages
```bash
# Install FPM dependencies
sudo apt update
sudo apt install ruby ruby-dev rubygems build-essential dpkg-dev
sudo gem install --no-document fpm

# Build package (no virtual environment or Python dependencies needed)
python scripts/build.py --format fpm
```

**Note**: FPM builds don't require installing Python runtime dependencies. The build script creates a wheel and packages it with proper dependency declarations for the package manager to handle.

#### Windows Packages
```bash
# With virtual environment activated
python scripts/build.py --format portable    # ZIP archive
python scripts/build.py --format onefile     # Single EXE
python scripts/build.py --format installer   # Windows installer
```

### 🔧 Build Troubleshooting

#### Missing PyInstaller Error (for Windows/portable builds)
```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Then retry building
python scripts/build.py --format portable
```

#### Missing FPM Dependencies (Linux package builds)
If you see `[ERROR] Missing FPM dependencies`:

```bash
# Ubuntu/Debian:
sudo apt update
sudo apt install ruby ruby-dev rubygems build-essential dpkg-dev
sudo gem install --no-document fpm

# Fedora/RHEL:
sudo dnf install ruby ruby-devel rubygems rpm-build gcc make
sudo gem install --no-document fpm

# Arch Linux:
sudo pacman -S ruby rubygems base-devel
sudo gem install --no-document fpm

# Then retry build
python scripts/build.py --format fpm
```

---

## 🔧 Troubleshooting

### Common Issues

#### Compilation Errors (Linux)
If you see "Python.h: No such file or directory":
```bash
# Ubuntu/Debian
sudo apt install python3-dev gcc build-essential

# Fedora/RHEL
sudo dnf install python3-devel gcc

# Then retry installation
pip install -r requirements.txt
```

#### Dependency Errors (Linux)
For "Dependency 'girepository-2.0' is required but not found" or similar errors:
```bash
# Install comprehensive system dependencies
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-tk libgirepository1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-3.0

# Install PyGObject
pip install PyGObject
```

### Feature Availability

| Feature | Always Available | Optional Dependencies |
|---------|-----------------|----------------------|
| Web UI | ✅ | - |
| API Server | ✅ | - |
| File Management | ✅ | - |
| Process Control | ✅ | - |
| Screenshots | ✅ | - |
| System Tray | ✅ (with fallback) | pystray, PyGObject (Linux native) |
| Input Control | ✅ (with fallback) | pynput |

**Note**: PCLink gracefully falls back to alternative implementations if dependencies are missing. All core functionality remains available.

---

## 🏗️ Architecture

### 🌐 Web-First Stack
* **Frontend**: Modern HTML5/CSS3/JavaScript with WebSocket
* **Backend**: FastAPI + Uvicorn ASGI server
* **Authentication**: Session-based with PBKDF2 password hashing
* **System Tray**: Cross-platform `pystray` (lightweight)
* **Security**: HTTPS + API keys + web authentication
* **Packaging**: Minimal dependencies, easy deployment

### 📁 Project Structure
```
src/pclink/
├── api_server/      # FastAPI routers + WebSocket handlers
├── core/            # Controller, auth, config, security
├── web_ui/          # Modern web interface (HTML/CSS/JS)
│   └── static/      # Web assets, authentication pages
└── assets/          # Icons and resources
```

### 🛠️ API Endpoints

**Public:**
- `/ui/` - Web interface (with auth)
- `/auth/*` - Authentication endpoints
- `/status` - Server health check

**Protected (API Key):**
- `/system/*` - Power, volume, processes
- `/info/*` - System and media information  
- `/input/*` - Remote keyboard/mouse control
- `/media/*` - Playback control
- `/files/*` - File browser and operations
- `/terminal/*` - WebSocket shell access
- `/ws` - WebSocket for real-time communication

**Web UI (Session Auth):**
- `/devices` - Connected device management
- `/logs` - Server log viewing
- `/qr-payload` - QR code generation data

---

## 🔒 Security

### 🌐 Web Interface Security
* **Password Authentication**: PBKDF2-hashed passwords with salt
* **Session Management**: Secure HTTP-only cookies with 24-hour timeout
* **IP Validation**: Session tied to client IP address
* **Automatic Cleanup**: Expired sessions automatically removed

### 📱 Mobile Device Security  
* **HTTPS Only**: Encrypted communication with auto-generated certificates
* **API Key Authentication**: Unique keys per device
* **Device Approval**: Manual pairing approval required
* **QR Code Pairing**: Secure visual pairing process
* **Device Revocation**: Instant access removal capability

### 🛡️ System Security
* **Single Instance**: Prevents multiple server conflicts
* **Local Certificates**: Self-signed HTTPS certificates
* **No HTTP Fallback**: HTTPS enforcement
* **Secure Defaults**: All security features enabled by default

---

## 📄 License

**GNU AGPL v3** – Free to use, modify, and distribute.
⚠️ Proprietary services must open-source modifications.
For commercial licensing, contact BYTEDz.

---

## 📞 Support

* **Support**: [support@bytedz.xyz](mailto:support@bytedz.xyz)
* **Website**: [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)
* **Developers**: [GitHub Issues](https://github.com/BYTEDz/PCLink/issues) • [Discussions](https://github.com/BYTEDz/PCLink/discussions)

---

## � Mahintainers

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/AzharZouhir">
        <img src="https://github.com/AzharZouhir.png" width="100px;" alt="Azhar Zouhir"/>
        <br />
        <sub><b>Azhar Zouhir</b></sub>
      </a>
      <br />
      <sub>Creator & Lead Developer</sub>
      <br />
      <a href="mailto:support@bytedz.xyz">📧</a>
      <a href="https://github.com/AzharZouhir">💻</a>
    </td>
  </tr>
</table>

---

<div align="center">

🕊️ Free Palestine • 🇩🇿 Made with ❤️ in Algeria

</div>
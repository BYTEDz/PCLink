<div align="center">

![PCLink Banner](docs/assets/banner.svg)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/BYTEDz/pclink)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/BYTEDz/pclink?include_prereleases)](https://github.com/BYTEDz/pclink/releases)

</div>

---

<div align="center">

**PCLink** is a cross-platform desktop application that enables secure remote control and management of your PC from mobile devices or other computers. The server provides a comprehensive API with a Qt-based GUI for local management.

</div>

**Created by [AZHAR ZOUHIR](https://github.com/AzharZouhir) / BYTEDz**

> 📱 **Need the mobile app?** Get it at [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)

## 🚀 Features

### Core Functionality
- **Remote System Control**: File browsing, process management, terminal access
- **Media Control**: Media key simulation, clipboard sync, volume control
- **Screen Capture**: Screenshot functionality for remote monitoring
- **QR Code Setup**: Easy mobile device pairing via QR codes

### Security & Communication
- **Secure Communication**: HTTPS with self-signed certificates, API key authentication
- **Device Pairing**: Secure device authentication and management
- **API Key Management**: Regenerate keys, manage connected devices

### User Experience
- **Cross-Platform**: Windows, macOS, and Linux support
- **System Tray Integration**: Minimize to tray, startup with OS options
- **Multi-Language Support**: English, Arabic, Spanish, French
- **Dark Theme UI**: Modern Qt-based interface with consistent styling
- **Auto-Update System**: Automatic update checking with GitHub integration

### Developer Features
- **Comprehensive API**: FastAPI-based REST API with WebSocket support
- **Build System**: Unified build and release automation
- **Extensible Architecture**: Plugin-ready design for future enhancements


## 📱 Get the Mobile App

**PCLink requires a companion mobile app to function.** The server alone is not useful without the mobile client.

### Download Options:
- 🌐 **Official Website**: [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)
- 📱 **Google Play Store**: [Download for Android](https://bytedz.xyz/products/pclink/) 
- 🍎 **iOS App Store**: Coming soon for iPhone/iPad

**One-time purchase** • No subscriptions • Premium experience

## 🛠️ Installation

### Quick Start (Recommended)

1. **Download Pre-built Releases**: Visit [GitHub Releases](https://github.com/BYTEDz/pclink/releases) for ready-to-use executables
2. **Get the Mobile App**: Download from [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)
3. **Run PCLink**: Start the server and scan the QR code with your mobile app

### From Source

```bash
# Clone the repository
git clone https://github.com/BYTEDz/pclink.git
cd pclink

# Install dependencies
pip install -r requirements.txt

# Run the application
python -m pclink                    # Run as a module
python src/pclink/__main__.py       # Run directly from source
python run_pclink.py               # Use convenience script
```

### Development Installation

```bash
# Install in development mode with all dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run tests
pytest
```

### Build Executable

```bash
# Using the build script (recommended)
python scripts/build.py

# Options:
python scripts/build.py --debug      # Debug build
python scripts/build.py --no-clean   # Skip cleaning previous builds
python scripts/build.py --builder nuitka  # Use Nuitka instead of PyInstaller

# Output: dist/PCLink/
```

## 🔧 Usage

### Quick Start Guide

1. **Download the mobile app**: Visit [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/) to get the companion app
2. **Start the server**: Run PCLink on your PC
3. **Get connection info**: Use the QR code or manual IP/port setup  
4. **Connect mobile app**: Scan QR code or enter connection details
5. **Control remotely**: Access files, media, terminal, and more

> ⚠️ **Important**: This server requires the PCLink mobile app to function. The server alone provides no user interface for remote control.

## 🏗️ Architecture

### Technology Stack
- **GUI Framework**: PySide6 (Qt for Python) with custom dark theme
- **API Server**: FastAPI with Uvicorn ASGI server
- **Build System**: PyInstaller/Nuitka for executable packaging
- **Security**: HTTPS with self-signed certificates, API key authentication
- **Update System**: GitHub API integration for automatic updates
- **Localization**: Multi-language support with Qt translation system

### Project Structure
```
pclink/
├── src/pclink/           # Main application source
│   ├── api_server/       # FastAPI server and endpoints
│   ├── core/            # Core functionality and utilities
│   └── gui/             # Qt GUI components and themes
├── scripts/             # Build and release automation
├── docs/               # Documentation and assets
├── tests/              # Test suite
└── assets/             # Application resources
```

### Build & Release System

PCLink uses a unified build and release system with automated GitHub Actions:

```bash
# Local development build
python scripts/build.py

# Create a new release (updates version, changelog, creates tag)
python scripts/release.py --version 1.2.0

# Build options
python scripts/build.py --debug          # Debug build
python scripts/build.py --no-clean       # Skip cleaning
python scripts/build.py --builder nuitka # Use Nuitka
```

**Automated Release Process:**
1. **Version Management**: Automatic version updates across all files
2. **Changelog Integration**: Moves unreleased changes to versioned sections
3. **Git Operations**: Creates tags, commits, and pushes to GitHub
4. **GitHub Actions**: Automatically builds releases for all platforms
5. **Update System**: Built-in update checker notifies users of new versions

### Auto-Update System

PCLink includes a built-in update checker that keeps your installation current:

**Features:**
- **Automatic Checking**: Checks for updates on startup (configurable)
- **Manual Updates**: "Check for Updates Now" in Settings menu
- **Smart Notifications**: Shows update dialog with release notes
- **Platform Detection**: Automatically detects appropriate download for your OS
- **User Control**: Skip versions, disable auto-check, or remind later

**How it Works:**
- Uses GitHub's public API (no authentication required)
- Compares current version with latest GitHub release
- Shows styled update dialog matching app theme
- Opens browser to download page or specific installer

**For Developers:**
- No API keys needed - uses public GitHub releases API
- Rate limited to 60 requests/hour (more than sufficient)
- Respects semantic versioning for update detection

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

**Created by AZHAR ZOUHIR / BYTEDz**

### Development Setup

```bash
# Clone and setup
git clone https://github.com/BYTEDz/pclink.git
cd pclink

# Install development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run in development mode
python -m pclink                    # Standard run
python -m pclink --startup         # Headless mode

# Testing and quality
pytest                              # Run tests
black src tests                     # Format code
isort src tests                     # Sort imports
pre-commit run --all-files         # Run all checks

# Build and release
python scripts/build.py             # Build executable
python scripts/release.py           # Create release
```

**Development Features:**
- **Hot Reload**: Automatic restart on code changes during development
- **Debug Mode**: Enhanced logging and error reporting
- **Test Suite**: Comprehensive testing with pytest
- **Code Quality**: Pre-commit hooks with black, isort, and flake8
- **Documentation**: Auto-generated API docs and user guides

## 📄 License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0).

### What this means:
- ✅ **Free to use** for personal and commercial purposes
- ✅ **Free to modify** and distribute
- ✅ **Source code access** guaranteed
- ⚠️ **Network services** using this code must provide source code to users
- ⚠️ **Modifications** must be shared under the same license

See the [LICENSE](LICENSE) file for full details.

### Business Model
- **Server**: Open source (AGPL v3) - free to use, modify, and distribute
- **Mobile App**: Proprietary - one-time purchase from [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)
- **Commercial Use**: If you want to use PCLink server in a proprietary network service without open-sourcing your modifications, please contact BYTEDz for commercial licensing options.

## 🔒 Security

### Communication Security
- **HTTPS Encryption**: All communication uses SSL/TLS encryption
- **Self-Signed Certificates**: Generated locally, no external dependencies
- **API Key Authentication**: Secure device pairing and access control
- **Certificate Fingerprinting**: Validates certificate authenticity

### Privacy & Data Protection
- **No External Servers**: All data stays on your local network
- **Local Processing**: No cloud services or data collection
- **Secure Pairing**: Device authentication with user confirmation
- **Update Privacy**: Update checks use public GitHub API only

### Access Control
- **Device Management**: View and manage connected devices
- **API Key Regeneration**: Revoke access for all devices instantly
- **Insecure Shell Warning**: Clear warnings for potentially risky features
- **Network Isolation**: Designed for trusted network environments

## 📞 Support

### For Users
- **Mobile App Support**: Visit [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/) for app-related help
- **General Questions**: Contact us through [bytedz.xyz](https://bytedz.xyz)

### For Developers  
- **Bug Reports**: [GitHub Issues](https://github.com/BYTEDz/pclink/issues)
- **Feature Discussions**: [GitHub Discussions](https://github.com/BYTEDz/pclink/discussions)
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md)

## 🙏 Acknowledgments

Built with:
- [PySide6](https://doc.qt.io/qtforpython/) - Qt for Python
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [PyInstaller](https://pyinstaller.org/) - Python packaging
- [Uvicorn](https://www.uvicorn.org/) - ASGI server

---

## 🏢 About BYTEDz

**PCLink** is developed by **BYTEDz**, creating premium mobile experiences with open source foundations.

- 🌐 **Website**: [bytedz.xyz](https://bytedz.xyz)
- 📱 **Products**: [bytedz.xyz/products](https://bytedz.xyz/products)
- � **GintHub**: [github.com/BYTEDz](https://github.com/BYTEDz)
- 💬 **Contact**: Available through our website

---

**PCLink Server** - Open source (AGPL v3) • **PCLink Mobile** - Premium app • **BYTEDz** - Quality software

---
<div align="center">

🕊️ Free Palestine • 🇩🇿 Made with ❤️ in Algeria

</div>
<div align="center">

![PCLink Banner](docs/assets/banner.svg)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/BYTEDz/pclink)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/BYTEDz/pclink?include_prereleases)](https://github.com/BYTEDz/pclink/releases)
[![Play Store](https://img.shields.io/badge/Android-Play%20Store-brightgreen?logo=google-play)](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)

</div>

---

<div align="center">

**PCLink** is a modern, cross-platform application for **secure remote PC control** from mobile devices.  
It features a **FastAPI server**, **Qt-based GUI**, and **headless background mode**.

</div>

**Created by [AZHAR ZOUHIR](https://github.com/AzharZouhir) / BYTEDz**

> 📱 **Need the mobile app?** Get it at [Google Play Store](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)

---

## 🚀 Features

### Core Functionality
- **Remote Control**: File browser, process manager, terminal access
- **Media & Input**: Media playback, keyboard/mouse input, clipboard sync
- **System Actions**: Shutdown, restart, volume control, system info
- **Screen Capture**: Remote screenshots
- **Device Discovery**: Network pairing via QR codes

### Security
- **HTTPS only** with auto-generated self-signed certificates
- **API Key Authentication** for devices
- **Single Instance Lock** to prevent conflicts
- **Secure Defaults**: No HTTP fallback

### User Experience
- **Cross-Platform**: Windows, macOS, Linux
- **Headless Mode**: Background server with tray integration
- **Unified Tray**: Consistent interface across modes
- **Multi-Language**: English, Arabic, Spanish, French
- **Auto-Update**: GitHub release-based updates

### Developer Features
- **Modular API Server**: Router-based FastAPI endpoints
- **Extensible Architecture**: Clear separation between API, Core, GUI
- **Unified Build System**: PyInstaller + Inno Setup
- **Testing & Dev Tools**: pytest, pre-commit, CI-ready

---

## 📱 Mobile App Required

The server requires the companion mobile app:

- 🌐 [Official Website](https://bytedz.xyz/products/pclink/)
- 📱 [Google Play](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)  
- 🍎 iOS: Coming soon

---

## 🛠️ Installation

### Quick Start
```bash
# Download PCLink Server release
# Install mobile app from Play Store
# Run server and scan QR code
````

### From Source

```bash
git clone https://github.com/BYTEDz/pclink.git
cd pclink
pip install -r requirements.txt
python -m pclink
```

### Development Setup

```bash
pip install -e ".[dev]"
pre-commit install
pytest
```

### Build Executable (PyInstaller + Inno Setup)

```bash
python scripts/build.py --builder pyinstaller
# Use Inno Setup script for installer generation
```

---

## 🏗️ Architecture

### Stack

* **GUI**: PySide6 (Qt)
* **API**: FastAPI + Uvicorn
* **Packaging**: PyInstaller + Inno Setup
* **Security**: HTTPS + API keys
* **Updates**: GitHub releases API

### Project Structure

```
src/pclink/
├── api_server/      # FastAPI routers: system, media, input, terminal, utils
├── core/            # Controller, config, security, state
├── gui/             # PySide6 GUI, tray, dialogs
├── assets/          # Icons, Play Store icon, resources
```

### Key Components

* **Headless Mode**: Background server with tray
* **Unified Tray Manager**: Shared tray across modes
* **Controller**: Central orchestration
* **Security**: HTTPS + API key enforcement
* **Modular API Routers**:

  * system\_router.py: Power & volume
  * info\_router.py: System/Media info
  * input\_router.py: Remote input
  * media\_router.py: Playback control
  * utils\_router.py: Clipboard, screenshots
  * file\_browser.py: File operations
  * process\_manager.py: Process control
  * terminal.py: WebSocket shell

---

## 🔒 Security

* Encrypted HTTPS communication only
* Local certificate generation
* API key authentication for device access
* Secure device pairing with QR codes

---

## 📄 License

**GNU AGPL v3** – Free to use, modify, and distribute.
⚠️ Proprietary services must open-source modifications.
For commercial licensing, contact BYTEDz.

---

## 📞 Support

* **Users**: [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)
* **Developers**: [GitHub Issues](https://github.com/BYTEDz/pclink/issues) • [Discussions](https://github.com/BYTEDz/pclink/discussions)

---

<div align="center">

🕊️ Free Palestine • 🇩🇿 Made with ❤️ in Algeria

</div>
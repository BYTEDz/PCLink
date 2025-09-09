<div align="center">

![PCLink Banner](docs/assets/banner.svg)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/BYTEDz/pclink)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/BYTEDz/pclink?include_prereleases)](https://github.com/BYTEDz/pclink/releases)

</div>

---

<div align="center">

**PCLink** is a secure, cross-platform application that enables **remote control and management of PCs** from mobile devices.  
It combines a modular **FastAPI server**, a **Qt-based GUI**, and a flexible **headless mode** for background operation.

</div>

**Created by [AZHAR ZOUHIR](https://github.com/AzharZouhir) / BYTEDz**

> 📱 **Need the mobile app?** Get it at [bytedz.xyz/products/pclink](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)

---

## 🚀 Features

### Core Functionality
- **Remote Control**: File browser, process manager, terminal access
- **Media & Input**: Media playback control, keyboard/mouse input, clipboard sync
- **System Actions**: Shutdown, restart, volume control, system info
- **Screen Capture**: Remote screenshot support
- **Device Discovery**: Local network pairing with QR codes

### Security
- **Mandatory HTTPS** with self-signed certificates (auto-generated)
- **API Key Authentication** for secure device pairing
- **System-wide Single Instance** lock prevents conflicts
- **Secure Defaults**: No HTTP fallback

### User Experience
- **Cross-Platform**: Windows, macOS, Linux
- **Headless Mode**: Run as a background service with tray integration
- **Unified Tray System**: Consistent controls across GUI & headless
- **Multi-Language Support**: English, Arabic, Spanish, French
- **Auto-Update**: Integrated update checker with GitHub releases

### Developer Features
- **Modular API Server**: Router-based FastAPI endpoints
- **Extensible Architecture**: Clear separation between API, Core, GUI
- **Unified Build System**: PyInstaller / Nuitka with automated release
- **Testing & Dev Tools**: pytest, pre-commit hooks, CI-ready

---

## 📱 Mobile App Required

PCLink server is **not standalone** – it requires the companion mobile app.

- 🌐 [Official Website](https://bytedz.xyz/products/pclink/)
- 📱 [Google Play](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)  
- 🍎 iOS: Coming soon

---

## 🛠️ Installation

### Quick Start
1. Download [PCLink Server Releases](https://github.com/BYTEDz/pclink/releases)  
2. Install the [Mobile App](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)  
3. Run PCLink → Scan QR code with your phone  

### From Source
```bash
git clone https://github.com/BYTEDz/pclink.git
cd pclink
pip install -r requirements.txt
python -m pclink
````

### Development Setup

```bash
pip install -e ".[dev]"
pre-commit install
pytest
```

### Build Executable

```bash
python scripts/build.py --builder nuitka
```

---

## 🏗️ Architecture

### Technology Stack

* **GUI**: PySide6 (Qt for Python)
* **API Server**: FastAPI + Uvicorn
* **Packaging**: PyInstaller / Nuitka
* **Security**: HTTPS, API key auth
* **Updates**: GitHub releases API

### Project Structure

```
src/pclink/
├── api_server/   # FastAPI routers (system, media, input, terminal, utils)
├── core/         # Business logic, config, controller, security
├── gui/          # PySide6 GUI, tray, dialogs
├── assets/       # Icons and static resources
```

### Key Components

* **Headless Mode** (`headless.py`): Background server with tray
* **Unified Tray Manager** (`tray_manager.py`): Shared tray between modes
* **Controller** (`controller.py`): Central app orchestrator
* **Security** (`security.py`): HTTPS + API key enforcement
* **Modular API Routers**:

  * `system_router.py`: Power & volume
  * `info_router.py`: System/Media info
  * `input_router.py`: Remote input
  * `media_router.py`: Playback control
  * `utils_router.py`: Clipboard, screenshots
  * `file_browser.py`: File operations
  * `process_manager.py`: Process control
  * `terminal.py`: WebSocket shell

---

## 🔒 Security

* Encrypted HTTPS traffic only
* Local certificates auto-generated
* API key authentication for all requests
* Device management via QR pairing

---

## 📄 License

**GNU AGPL v3** – Free to use, modify, and distribute.
⚠️ Proprietary services using PCLink must open-source their modifications.
For commercial licensing, contact BYTEDz.

---

## 📞 Support

* **Users**: [bytedz.xyz/products/pclink](https://bytedz.xyz/products/pclink/)
* **Developers**: [GitHub Issues](https://github.com/BYTEDz/pclink/issues) • [Discussions](https://github.com/BYTEDz/pclink/discussions)

---

<div align="center">

🕊️ Free Palestine • 🇩🇿 Made with ❤️ in Algeria

</div>

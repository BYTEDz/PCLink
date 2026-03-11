<div align="center">

<img src="assets/pclink_logo.svg" width="120" alt="PCLink Logo">

# PCLink Server

**The secure backbone for your personal PC remote control ecosystem.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux-lightgrey?style=for-the-badge)](https://github.com/BYTEDz/PCLink)
[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Play Store](https://img.shields.io/badge/Android-Play%20Store-3DDC84?style=for-the-badge&logo=google-play&logoColor=white)](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)

PCLink is a modern, **web-first** server designed for **secure remote PC management**.  
Featuring a high-performance FastAPI backend, a responsive Web UI, and an extensible plugin system.

[**Download Releases**](https://github.com/BYTEDz/PCLink/releases) • [**Mobile App**](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink) • [**Wiki Portal**](https://github.com/BYTEDz/PCLink/wiki)

</div>

## 🚀 Quick Start

### 1. Install

Choose your platform to install the PCLink server:

- **🐧 Linux (Automated):**
  ```bash
  bash <(curl -fsSL https://raw.githubusercontent.com/BYTEDz/PCLink/main/install.sh)
  ```
- **🪟 Windows:** Download the [`.exe` installer](https://github.com/BYTEDz/PCLink/releases).
- **📦 Arch Linux:** Available on the AUR (maintained by [Mark Wagie](https://github.com/yochananmarqos)). Install with `yay -S pclink`.
- **⚙️ Manual:** Grab the [`.deb` or `.rpm`](https://github.com/BYTEDz/PCLink/releases) packages from the releases page.

### 2. Launch

Start the PCLink server on your machine:

```bash
pclink
```

### 3. Pair & Connect

1. Open `https://localhost:38080/ui/` in your desktop browser.
2. Open the **PCLink Mobile App**.
3. Scan the QR code displayed on your Web UI and approve the connection.

> [!NOTE]  
> New to PCLink? Check out the comprehensive [**Getting Started Guide**](https://github.com/BYTEDz/PCLink/wiki/Getting-Started).

> [!IMPORTANT]  
> **Antivirus Notice:** PCLink integrates deeply with your system (remote input, screen capture, terminal access). This can occasionally trigger **False Positive** alerts (e.g., `Wacatac.B!ml`) from Windows Defender. Every release is verified via VirusTotal. This project is 100% Open Source and transparent.

---

## 🎨 Key Features

- **🌐 Web-First Management** – Configure your server and manage paired devices entirely from your browser.
- **🛡️ Zero-Trust Security** – Mandatory HTTPS, manual device approval, and cryptographically secure sessions.
- **⌨️ Peripheral Sync** – Seamlessly control your remote keyboard, mouse, system volume, and media playback.
- **📂 Remote Explorer** – Full-featured remote file browser and system process manager.
- **💻 Integrated Shell** – WebSocket-powered terminal access for remote CLI management.
- **🧩 Extensible Architecture** – Add capabilities via the built-in [Extension System](https://github.com/BYTEDz/PCLink/wiki/Extension-Development).

---

## 🏗️ Documentation Hub

Whether you're a user or a developer, we have you covered in our **[Project Wiki](https://github.com/BYTEDz/PCLink/wiki)**.

| 📚 User Guides                                                                              | 🛠️ Development                                                                         | ⚙️ Reference                                                                  |
| :------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------- |
| 📖 [Getting Started](https://github.com/BYTEDz/PCLink/wiki/Getting-Started)                 | 🏗️ [Build from Source](https://github.com/BYTEDz/PCLink/wiki/Building-and-Development) | 🔌 [API Endpoints](https://github.com/BYTEDz/PCLink/wiki/API-Endpoints)       |
| 🌐 [Web UI Guide](https://github.com/BYTEDz/PCLink/wiki/Web-UI)                             | 🧩 [Extension SDK](https://github.com/BYTEDz/PCLink/wiki/Extension-Development)        | 🔒[Security Model](https://github.com/BYTEDz/PCLink/wiki/Server-Architecture) |
| ⚠️ [Troubleshooting](https://github.com/BYTEDz/PCLink/wiki/Getting-Started#troubleshooting) | 🤝 [Contributing](https://github.com/BYTEDz/PCLink/wiki/Contributing)                  | ⚡ [Quick Commands](https://github.com/BYTEDz/PCLink/wiki/Quick-Reference)    |

---

## 🌐 The Ecosystem & Activity

Join the wider PCLink ecosystem:

- 🏠 **[PCLink Server](https://github.com/BYTEDz/PCLink)** – The core backend service.
- 📱 **[PCLink Mobile](https://play.google.com/store/apps/details?id=xyz.bytedz.pclink)** – Companion app for Android.
- 📦 **[PCLink Extensions](https://github.com/BYTEDz/pclink-extensions)** – Official repository for community extensions.

<div align="center">

[![GitHub Release Date](https://img.shields.io/github/release-date/BYTEDz/PCLink?style=flat-square&color=blue)](https://github.com/BYTEDz/PCLink/releases) [![GitHub Last Commit](https://img.shields.io/github/last-commit/BYTEDz/PCLink?style=flat-square&color=green)](https://github.com/BYTEDz/PCLink/commits/main) [![GitHub Issues](https://img.shields.io/github/issues/BYTEDz/PCLink?style=flat-square&color=orange)](https://github.com/BYTEDz/PCLink/issues)

[![PCLink Stars](https://starchart.cc/BYTEDz/PCLink.svg?variant=adaptive)](https://starchart.cc/BYTEDz/PCLink)

</div>

---

## 🤝 Support & Maintainers

<div align="center">

<a href="https://github.com/AzharZouhir">
  <img src="https://github.com/AzharZouhir.png" width="100px" style="border-radius: 50%; border: 3px solid #3d76ab;" alt="Azhar Zouhir"/>
</a>

**[Azhar Zouhir](https://github.com/AzharZouhir)**  
_Creator & Lead Developer_  
Building the next generation of PC remote management.

[![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/AzharZouhir) [![Email](https://img.shields.io/badge/Email-D14836?style=flat-square&logo=gmail&logoColor=white)](mailto:support@bytedz.com)

🕊️ Free Palestine • 🇩🇿 Made with ❤️ in Algeria

</div>

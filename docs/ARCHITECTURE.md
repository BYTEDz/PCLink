# PCLink Architecture & Source Code Structure

This document provides a comprehensive overview of the PCLink project's source code architecture, explaining how all components are interconnected and work together.

## Overview

PCLink is a cross-platform desktop application that enables secure remote control of PCs from mobile devices. The architecture follows a modular design with clear separation of concerns between GUI, API server, and core business logic.

## Source Code Structure (`src/pclink/`)

```
src/pclink/
├── __init__.py
├── __main__.py             # Module entry point (python -m pclink)
├── launcher.py             # Standalone launcher for packaged apps
├── main.py                 # Main entry point, launches GUI or Headless mode
├── headless.py             # Headless/background application manager
│
├── api_server/             # FastAPI REST API server
│   ├── __init__.py
│   ├── api.py              # Main API router aggregator & WebSocket hub
│   ├── discovery.py        # Network discovery and device pairing
│   ├── file_browser.py     # File system operations API
│   ├── info_router.py      # System and media information endpoints
│   ├── input_router.py     # Remote keyboard/mouse input endpoint
│   ├── media_router.py     # Media control endpoints (play/pause, seek)
│   ├── process_manager.py  # System process management API
│   ├── services.py         # Shared API logic and helper functions
│   ├── system_router.py    # System command endpoints (power, volume)
│   ├── terminal.py         # Terminal/shell access API
│   └── utils_router.py     # Utility endpoints (clipboard, screenshot)
│
├── core/                   # Core business logic and utilities
│   ├── __init__.py
│   ├── config.py           # Centralized configuration management
│   ├── constants.py        # Application constants and paths (incl. AUMID)
│   ├── controller.py       # Main application controller
│   ├── device_manager.py   # Device connection management
│   ├── exceptions.py       # Custom exception classes
│   ├── logging_config.py   # Logging configuration
│   ├── security.py         # Security helpers (auth, certs, crypto)
│   ├── setup_guide.py      # First-time setup guide
│   ├── singleton.py        # System-wide single instance lock
│   ├── state.py            # Global application state
│   ├── update_checker.py   # Auto-update functionality
│   ├── utils.py            # General utility functions
│   ├── validators.py       # Input validation and sanitization
│   ├── version.py          # Version information (__version__)
│   └── windows_console.py  # Windows-specific console integration
│
├── gui/                    # PySide6 GUI components
│   ├── __init__.py
│   ├── discovery_dialog.py # Device pairing dialog
│   ├── layout.py           # UI layout and widget setup
│   ├── localizations.py    # Multi-language support
│   ├── main_window.py      # Main application window
│   ├── theme.py            # Dark theme and app icon handling
│   ├── tray_manager.py     # Unified system tray icon and menu
│   ├── update_dialog.py    # Update notification dialogs
│   ├── version_dialog.py   # Version information dialog
│   └── windows_notifier.py # Native Windows Toast Notification handler
│
└── assets/                 # Static resources
    ├── icon.ico            # Windows icon
    ├── icon.png            # PNG icon
    └── icon.svg            # SVG icon
```

📂 **46 files, 4 folders**

---

## Application Architecture

### Entry Points and Application Flow

#### 1. Entry Points

* **`__main__.py`**: Module entry point for `python -m pclink`.
* **`launcher.py`**: Standalone launcher for packaged applications.
* **`main.py`**: Refactored startup logic, manages singleton enforcement, GUI/headless detection, setup guide prompts, and error handling.

#### 2. Application Modes

PCLink operates in two distinct modes:

**GUI Mode (`MainWindow` in `gui/main_window.py`)**

* Qt-based interface.
* Integrates `UnifiedTrayManager`.
* Automatically launches API server.
* Handles update checks and QR-based pairing.

**Headless Mode (`HeadlessApp` in `headless.py`)**

* Lightweight background server at system startup.
* Provides tray controls via `tray_manager.py`.
* Can spawn the full GUI on demand.

---

### Core Architecture Components

#### 1. Singleton Pattern (`PCLinkSingleton` in `core/singleton.py`)

Guarantees only one active PCLink process (mutex/file lock).

#### 2. Unified Tray System (`UnifiedTrayManager` in `gui/tray_manager.py`)

Refactored to provide consistent tray menus across GUI and headless modes.

#### 3. Controller Pattern (`Controller` in `core/controller.py`)

Central orchestrator for app logic—manages server lifecycle, device connections, and UI state sync.

#### 4. Security Layer (`security.py` in `core/`)

Introduced to consolidate authentication, certificate, and crypto logic.

---

### Modular API Server

#### `api_server/api.py`

* Now router-based: imports and registers specialized routers.
* Manages WebSockets, authentication, and device pairing.
* HTTPS-only (HTTP option removed).

#### Specialized Routers

* **`system_router.py`**: Power commands & volume control.
* **`info_router.py`**: CPU, RAM, OS, disk, and media info.
* **`input_router.py`**: Keyboard/mouse input.
* **`media_router.py`**: Media playback (play/pause, seek).
* **`utils_router.py`**: Clipboard and screenshots.
* **`file_browser.py`**: File browsing, paste/delete endpoints.
* **`process_manager.py`**: Process lifecycle control.
* **`terminal.py`**: WebSocket-based terminal access.

#### Shared Services (`services.py`)

API helpers for input, system info, device state.

---

### GUI Integration

* **`main_window.py`**: Heavily refactored; handles device list, QR codes, update dialogs, and tray integration.
* **`theme.py`**: Improved icons (`create_app_icon`, fallback handling).
* **`windows_notifier.py`**: Native Windows toast notifications.

---

### Security & Configuration

* **Authentication**: API key (UUID).
* **Transport Security**: HTTPS mandatory (self-signed certs generated on first run).
* **Config Management**: Centralized in `core/config.py`.

---

### Cross-Platform Enhancements

* **`windows_console.py`**: Windows-specific console utilities.
* **`security.py`**: Shared across OSes.
* **Logging**: Unified via `core/logging_config.py`.

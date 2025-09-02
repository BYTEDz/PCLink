# PCLink Architecture & Source Code Structure

This document provides a comprehensive overview of the PCLink project's source code architecture, explaining how all components are interconnected and work together.

## Overview

PCLink is a cross-platform desktop application that enables secure remote control of PCs from mobile devices. The architecture follows a modular design with clear separation of concerns between GUI, API server, and core business logic.

## Source Code Structure (`src/pclink/`)

```
src/pclink/
├── __init__.py             # Package initialization
├── __main__.py             # Module entry point (python -m pclink)
├── launcher.py             # Standalone launcher for packaged apps
├── main.py                 # Main entry point, launches GUI or Headless mode
├── headless.py             # Headless/background application manager
│
├── api_server/             # FastAPI REST API server
│   ├── __init__.py
│   ├── api.py              # Main API router aggregator and WebSocket hub
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
│   ├── config.py           # Configuration management
│   ├── constants.py        # Application constants and paths (incl. AUMID)
│   ├── controller.py       # Main application controller
│   ├── device_manager.py   # Device connection management
│   ├── exceptions.py       # Custom exception classes
│   ├── logging_config.py   # Logging configuration
│   ├── setup_guide.py      # First-time setup guide
│   ├── singleton.py        # System-wide single instance lock
│   ├── state.py            # Global application state
│   ├── update_checker.py   # Auto-update functionality
│   ├── utils.py            # General utility functions
│   ├── validators.py       # Input validation and sanitization
│   └── version.py          # Version information
│
├── gui/                    # PySide6 GUI components
│   ├── __init__.py
│   ├── discovery_dialog.py # Device pairing dialog
│   ├── layout.py           # UI layout and widget setup
│   ├── localizations.py    # Multi-language support
│   ├── main_window.py      # Main application window
│   ├── theme.py            # Dark theme and styling
│   ├── tray_manager.py     # System tray icon and menu management
│   ├── update_dialog.py    # Update notification dialogs
│   ├── version_dialog.py   # Version information dialog
│   └── windows_notifier.py # Native Windows Toast Notification handler
│
└── assets/                 # Static resources
    ├── icon.ico            # Windows icon
    ├── icon.png            # PNG icon
    └── icon.svg            # SVG icon
```

## Application Architecture

### Entry Points and Application Flow

#### 1. Entry Points
- **`__main__.py`**: Module entry point for `python -m pclink`.
- **`launcher.py`**: Standalone launcher for packaged applications.
- **`main.py`**: Main application entry point responsible for launching GUI or Headless mode.

#### 2. Application Modes
PCLink operates in two distinct modes, now managed by separate classes:

**GUI Mode (`MainWindow` in `gui/main_window.py`)**:
- Full Qt-based graphical interface.
- Manages its own lifecycle and system tray via `gui/tray_manager.py`.
- Automatically starts the server on launch for a seamless user experience.

**Headless Mode (`HeadlessApp` in `headless.py`)**:
- Background server operation for system startup.
- Provides a minimal system tray menu via `gui/tray_manager.py`.
- Can spawn the full GUI on demand, ensuring a smooth transition.

### Core Architecture Components

#### 1. Singleton Pattern (`PCLinkSingleton` in `core/singleton.py`)
Ensures only one PCLink instance runs system-wide using a platform-native locking mechanism (Windows mutex, Unix file lock).

#### 2. Unified Tray System (`UnifiedTrayManager` in `gui/tray_manager.py`)
Provides a consistent system tray experience across modes with mode-aware menu generation, server status updates, and GUI switching.

#### 3. Controller Pattern (`Controller` in `core/controller.py`)
The central orchestrator for application logic, managing the server lifecycle, device connections, and UI state synchronization for both GUI and headless modes.

### Component Interconnections

#### Modular API Server Architecture

The API server has been refactored from a monolithic file into a modular, router-based architecture for improved maintainability and separation of concerns.

**`api_server/api.py`** - Main FastAPI Application
- Acts as a router aggregator, importing and including all specialized router modules.
- Manages core functionalities like authentication (API key verification), CORS, WebSockets, and device pairing.

**`api_server/services.py`** - Shared Services
- Provides shared logic and helper functions (e.g., remote input controllers, system info providers) used by multiple routers to avoid code duplication and circular dependencies.

**Specialized API Routers**:
- **`system_router.py`**: Handles core system actions like power commands (shutdown, reboot) and master volume control.
- **`info_router.py`**: Provides endpoints for querying system information (CPU, RAM, OS, disks).
- **`input_router.py`**: Manages remote keyboard input.
- **`media_router.py`**: Controls media playback (play/pause, next/previous track) and provides media info.
- **`utils_router.py`**: Exposes utility functions like clipboard access and screenshotting.
- **`file_browser.py`**, **`process_manager.py`**, **`terminal.py`**: Retain their specialized roles.

#### GUI Component Integration

- **`gui/main_window.py`**: The primary GUI window. It initializes the `Controller` and `UnifiedTrayManager` for its lifecycle.
- **`headless.py`**: The headless application manager. It also initializes a `Controller` and `UnifiedTrayManager` for its lifecycle, transitioning control to `MainWindow` when the GUI is requested.

### Data Flow and Communication

#### API Request Flow
```
Mobile App → HTTPS Request → api.py → Specific Router Module (e.g., system_router.py) → System Operation → Response
```

### Security Architecture

#### Authentication & Authorization
- **API Key**: UUID-based authentication for all API endpoints.
- **HTTPS Enforcement**: Communication is now **exclusively over HTTPS**, enforced by default. The optional HTTP mode has been removed to enhance security.
- **Self-Signed Certificates**: Automatically generated by `core/utils.py` on the first run to ensure all local network traffic is encrypted.

### Configuration Management

- The `use_https` setting has been removed from `core/config.py` as HTTPS is now mandatory.
- All other settings are managed centrally through the `ConfigManager` singleton.
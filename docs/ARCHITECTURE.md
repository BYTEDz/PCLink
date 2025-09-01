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
├── main.py                 # Main application entry point and GUI
│
├── api_server/             # FastAPI REST API server
│   ├── __init__.py
│   ├── api.py              # Main API routes and FastAPI app
│   ├── discovery.py        # Network discovery and device pairing
│   ├── file_browser.py     # File system operations API
│   ├── process_manager.py  # System process management API
│   └── terminal.py         # Terminal/shell access API
│
├── core/                   # Core business logic and utilities
│   ├── __init__.py
│   ├── config.py           # Configuration management
│   ├── constants.py        # Application constants and paths
│   ├── controller.py       # Main application controller
│   ├── device_manager.py   # Device connection management
│   ├── exceptions.py       # Custom exception classes
│   ├── logging_config.py   # Logging configuration
│   ├── security.py         # Security utilities and certificates
│   ├── setup_guide.py      # First-time setup guide
│   ├── state.py            # Global application state
│   ├── update_checker.py   # Auto-update functionality
│   ├── utils.py            # General utility functions
│   ├── validators.py       # Input validation and sanitization
│   ├── version.py          # Version information
│   └── windows_console.py  # Windows-specific console utilities
│
├── gui/                    # PySide6 GUI components
│   ├── __init__.py
│   ├── discovery_dialog.py # Device pairing dialog
│   ├── layout.py           # UI layout and widget setup
│   ├── localizations.py    # Multi-language support
│   ├── main_window.py      # Main application window
│   ├── theme.py            # Dark theme and styling
│   ├── update_dialog.py    # Update notification dialogs
│   └── version_dialog.py   # Version information dialog
│
└── assets/                 # Static resources
    ├── icon.ico            # Windows icon
    ├── icon.png            # PNG icon
    └── icon.svg            # SVG icon
```

## Application Architecture

### Entry Points and Application Flow

#### 1. Entry Points
- **`__main__.py`**: Module entry point for `python -m pclink`
- **`launcher.py`**: Standalone launcher for packaged applications
- **`main.py`**: Main application entry point containing GUI and headless modes

#### 2. Application Modes
PCLink operates in two distinct modes:

**GUI Mode (`MainWindow`)**:
- Full Qt-based graphical interface
- System tray integration
- Real-time device management
- Interactive configuration

**Headless Mode (`HeadlessApp`)**:
- Background server operation
- Minimal system tray menu
- Can spawn GUI on demand
- Ideal for server deployments

### Core Architecture Components

#### 1. Singleton Pattern (`PCLinkSingleton`)
Ensures only one PCLink instance runs system-wide:
- Cross-platform instance locking (Windows mutex, Unix file lock)
- Manages application and tray manager instances
- Prevents multiple server conflicts

#### 2. Unified Tray System (`UnifiedTrayManager`)
Provides consistent system tray experience across modes:
- Mode-aware menu generation
- Server status updates
- Cross-mode GUI switching
- Debug and utility access

#### 3. Controller Pattern (`Controller`)
Central orchestrator for application logic:
- Server lifecycle management
- Device connection handling
- UI state synchronization
- API server coordination

### Component Interconnections

#### Core Module Dependencies

**`core/controller.py`** - Main Application Controller
- **Depends on**: `api_server/api.py`, `core/state.py`, `api_server/discovery.py`
- **Manages**: Server startup/shutdown, device connections, UI updates
- **Connects**: GUI events to API server operations

**`core/state.py`** - Global State Management
- **Provides**: Thread-safe device storage, Qt signal emission
- **Used by**: All modules requiring device state access
- **Pattern**: Observer pattern with Qt signals for GUI updates

**`core/device_manager.py`** - Device Connection Management
- **Integrates with**: `api_server/discovery.py`, `core/state.py`
- **Handles**: Device authentication, connection tracking, cleanup

#### API Server Architecture

**`api_server/api.py`** - Main FastAPI Application
- **Imports**: All other API modules as route collections
- **Provides**: Authentication, CORS, WebSocket support
- **Connects to**: `core/state.py` for device management

**`api_server/discovery.py`** - Network Discovery Service
- **Implements**: UDP broadcast discovery, device pairing
- **Integrates with**: `core/state.py` for device registration
- **Provides**: QR code generation for mobile app pairing

**Specialized API Modules**:
- **`file_browser.py`**: File system operations (browse, upload, download)
- **`process_manager.py`**: System process management and monitoring
- **`terminal.py`**: Shell/terminal access with WebSocket streaming

#### GUI Component Integration

**`gui/main_window.py`** - Primary GUI Window
- **Uses**: `gui/layout.py` for UI setup, `gui/theme.py` for styling
- **Connects to**: `core/controller.py` for business logic
- **Manages**: User interactions, real-time updates, dialogs

**`gui/layout.py`** - UI Layout Management
- **Provides**: Widget creation, layout setup, signal connections
- **Uses**: `gui/localizations.py` for multi-language support
- **Integrates with**: `core/state.py` for dynamic updates

**Dialog Components**:
- **`discovery_dialog.py`**: Device pairing interface
- **`update_dialog.py`**: Update notifications and installation
- **`version_dialog.py`**: Application information display

### Data Flow and Communication

#### 1. Device Connection Flow
```
Mobile App → UDP Discovery → discovery.py → device_manager.py → state.py → GUI Update
```

#### 2. API Request Flow
```
Mobile App → HTTPS Request → api.py → Specific API Module → System Operation → Response
```

#### 3. GUI Event Flow
```
User Action → main_window.py → controller.py → API Server → System Operation
```

#### 4. State Update Flow
```
API Server → state.py → Qt Signals → GUI Components → UI Update
```

### Security Architecture

#### Authentication & Authorization
- **API Key**: UUID-based authentication stored in `constants.API_KEY_FILE`
- **HTTPS**: Self-signed certificates generated by `core/security.py`
- **Device Pairing**: Secure pairing process through `api_server/discovery.py`

#### Input Validation
- **`core/validators.py`**: Centralized validation for all user inputs
- **API Level**: FastAPI Pydantic models for request validation
- **GUI Level**: Qt input validation and sanitization

### Configuration Management

#### Settings Storage
- **Qt Settings**: GUI preferences stored via `QSettings`
- **JSON Files**: API keys, ports, and server config in `constants.APP_DATA_PATH`
- **Runtime Config**: Managed through `core/config.py`

#### Multi-language Support
- **`gui/localizations.py`**: Translation dictionaries for supported languages
- **Dynamic Loading**: Language switching without restart
- **Fallback**: English as default for missing translations

### Build and Deployment

#### Application Packaging
- **PyInstaller**: Primary build tool for executable creation
- **Nuitka**: Alternative compiler for performance optimization
- **Cross-platform**: Windows, macOS, and Linux support

#### Asset Management
- **Icon Handling**: Multiple formats (ICO, PNG, SVG) for different platforms
- **Resource Path**: Dynamic resource location for both development and packaged modes
- **Fallback Icons**: Generated programmatically if assets missing

## Key Design Patterns

### 1. Model-View-Controller (MVC)
- **Model**: `core/state.py` - Application data and state
- **View**: `gui/` modules - User interface presentation
- **Controller**: `core/controller.py` - Business logic coordination

### 2. Observer Pattern
- **Qt Signals**: Used throughout for loose coupling
- **State Updates**: Automatic GUI updates on state changes
- **Event Driven**: Asynchronous communication between components

### 3. Singleton Pattern
- **Application Instance**: Ensures single running instance
- **Tray Manager**: Unified system tray across modes
- **Device Manager**: Centralized device state management

### 4. Factory Pattern
- **API App Creation**: Dynamic FastAPI app configuration
- **Icon Generation**: Fallback icon creation when assets missing
- **Dialog Creation**: Dynamic dialog instantiation based on context

## Performance Considerations

### Threading Model
- **Main Thread**: Qt GUI and event loop
- **Server Thread**: FastAPI/Uvicorn server
- **Discovery Thread**: UDP discovery service
- **Background Tasks**: Device cleanup, update checks

### Resource Management
- **Memory**: Efficient device state storage with automatic cleanup
- **Network**: Connection pooling and timeout management
- **File System**: Streaming for large file operations

### Scalability
- **Device Limit**: Configurable maximum connected devices
- **API Rate Limiting**: Built-in request throttling
- **Resource Monitoring**: System resource usage tracking

This architecture ensures PCLink remains maintainable, extensible, and performant while providing a seamless user experience across different deployment scenarios.
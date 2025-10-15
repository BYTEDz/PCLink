# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [2.1.0] - 2025-10-15

### Added
-   **Web-First Interface**: Replaced Qt GUI with a modern, web-based interface accessible via web browser.
-   **Web UI Authentication**:  Added password-protected login and session management for the web interface.
-   **Device Management in Web UI**:  Added ability to manage connected devices within the web UI, including approving and revoking access.
-   **System Tray Manager**: Implemented a cross-platform system tray manager without Qt dependencies.
-   **Background Server**: Added support for running the server in background mode with system tray integration.
-   **API Key Authentication**: Implemented a secure API key authentication for device access.
-   **Mobile Device Pairing**: Implemented secure pairing using QR codes.
-   **Update Checker**: Implemented update checker with version information.
-   **System Notification Integration**: Implemented cross-platform notifications
-   **Log Viewer**: Implemented log viewer
-   **Settings Management**: Added settings page to manage server settings
-   **First time setup**: added first time setup guide

### Changed
-   **Architecture Overhaul**: Transitioned from a Qt-based GUI to a web-first architecture.
-   **Core Components**: Refactored core components for the new architecture.
-   **Security Enhancements**: Implemented HTTPS-only communication, API key authentication, and secure pairing.
-   **Build System**: Enhanced the build system to support web-first mode and packaging.
-   **Licensing**: Updated license information to AGPLv3.

### Removed
-   **Qt GUI**: Removed the Qt-based GUI.
-   **Old GUI elements**: Removed old GUI elements such as QMainWindow and QListWidget from the layout
-   **Deprecated features**: Removed deprecated features to simplify the codebase.

### Fixed
-   **Various Bug Fixes**: Addressed various bug fixes and improved overall stability.
## [2.0.0] - 2025-09-09

- **Added**
    - `media_check.py`: Script to diagnose media session access.
    - `src/pclink/api_server/info_router.py`: Module for system and media information endpoints.
    - `src/pclink/api_server/input_router.py`: Module for handling keyboard input.
    - `src/pclink/api_server/media_router.py`: Module for controlling media playback.
    - `src/pclink/api_server/services.py`: Centralized API helper functions and controllers.
    - `src/pclink/api_server/system_router.py`: Module for system power and volume commands.
    - `src/pclink/api_server/terminal.py`: Module for WebSocket-based terminal access.
    - `src/pclink/api_server/utils_router.py`: Module for clipboard and screenshot utilities.
    - `src/pclink/core/config.py`: Centralized configuration management.
    - `src/pclink/core/controller.py`: Main application logic controller.
    - `src/pclink/core/setup_guide.py`: First-run setup guide and configuration logic.
    - `src/pclink/core/singleton.py`: Module to ensure single instance execution.
    - `src/pclink/gui/tray_manager.py`: Unified system tray icon management.
    - `src/pclink/gui/update_dialog.py`: Dialog for displaying update information.
    - `src/pclink/gui/windows_notifier.py`: Native Windows toast notification implementation.
    - `src/pclink/headless.py`: Headless application mode management.
- **Modified**
    - `requirements.txt`: Added `getmac>=0.9.4` and WinRT packages for media control.
    - `scripts/build.py`: Added `--uninstall` flag and `UninstallManager` class.
    - `src/pclink/api_server/api.py`:
        - Refactored to include new routers and services.
        - Removed duplicate Pydantic models.
        - Updated broadcast task logic.
        - Removed `use_https` from `create_api_app` as HTTPS is mandatory.
    - `src/pclink/api_server/discovery.py`: Improved initialization and logging.
    - `src/pclink/api_server/file_browser.py`:
        - Added `PastePayload` and `PathsPayload` models.
        - Implemented `delete_items` and `paste_items` endpoints.
        - Improved path validation and uniqueness handling.
    - `src/pclink/gui/main_window.py`:
        - Reworked initialization and signal handling.
        - Integrated `UnifiedTrayManager`.
        - Updated QR code generation and display logic.
        - Refactored settings loading and UI updates.
        - Updated device list display logic.
        - Implemented update check signals and dialog handling.
    - `src/pclink/gui/theme.py`: Added `create_app_icon` and `_create_fallback_icon`.
    - `src/pclink/main.py`:
        - Refactored startup logic.
        - Implemented singleton pattern for instance management.
        - Improved headless/GUI mode detection and transitions.
        - Integrated setup guide and configuration prompts.
        - Enhanced error handling and logging.
- **Renamed**
    - `src/pclink/api_server/discovery.py`: Renamed `_broadcast_loop` to include loop suffix.
    - `src/pclink/api_server/file_browser.py`: Renamed `path_payload` to `PathPayload`.
    - `src/pclink/core/version.py`: Renamed `version_info` to `__version__`.
## [1.3.0] - 2025-08-13

### Fixed
- **Discovery Issues**: Fixed Android devices unable to discover PCLink server due to Windows Firewall blocking UDP broadcasts
- **Pairing Dialog**: Fixed pairing dialog not appearing due to flawed duplicate detection mechanism
- **WebSocket Authentication**: Fixed WebSocket connections failing after device pairing by implementing device-based authentication
- **Device Management**: Fixed GUI device list not refreshing when devices connect/disconnect/reconnect

### Added
- **Discovery Troubleshooting**: Integrated "Fix Discovery Issues" dialog in Settings menu for one-click firewall rule management
- **Firewall Management**: Added automatic Windows Firewall rule creation for UDP port 38099 discovery broadcasts
- **Device Management Utility**: Added `clear_devices.py` utility for clearing registered devices when client app data is reset
- **Admin Privilege Handling**: Added automatic administrator privilege detection and restart functionality
- **Enhanced Device Tracking**: Added device last seen updates and GUI refresh signals for real-time device status

### Improved
- **Discovery Protocol**: Enhanced UDP broadcast system with better error handling and network diagnostics
- **Device Authentication**: Unified authentication system supporting both server API keys and device-specific API keys
- **GUI Integration**: Seamless integration of discovery troubleshooting tools directly in the application interface
- **User Experience**: Eliminated need for external batch files or command-line tools for common issues
- **Device State Management**: Improved device registration, approval, and revocation with proper GUI updates

### Technical Details
- **Discovery Service**: Enhanced UDP broadcast mechanism with comprehensive error handling
- **Device Manager**: Added GUI update signals to `approve_device()`, `update_device_ip()`, and `revoke_device()` methods
- **WebSocket Endpoint**: Updated authentication to support device-specific API keys alongside server API key
- **Pairing System**: Improved duplicate detection using `user_decided` flag instead of simple presence check
- **Firewall Utils**: Added `is_admin()`, `check_firewall_rule_exists()`, `add_firewall_rule()`, and `restart_as_admin()` utilities
- **Discovery Dialog**: Created comprehensive troubleshooting interface with background thread operations

### Files Modified
- `src/pclink/api_server/discovery.py`: Enhanced discovery service with better error handling
- `src/pclink/core/device_manager.py`: Added GUI update signals and device last seen tracking
- `src/pclink/api_server/api.py`: Updated WebSocket authentication and device management
- `src/pclink/core/controller.py`: Fixed pairing dialog duplicate detection and added discovery troubleshooting
- `src/pclink/core/utils.py`: Added Windows Firewall management utilities
- `src/pclink/gui/discovery_dialog.py`: New comprehensive discovery troubleshooting dialog
- `src/pclink/main.py`: Added discovery troubleshooting menu integration
## [1.2.0] - 2025-07-27

### Fixed
- **Pairing System**: Fixed "unexpected error" issues during client connection attempts
- **Duplicate Dialogs**: Resolved pairing dialog appearing twice when clients request pairing
- **Certificate Handling**: Fixed certificate generation with proper IPv4Address formatting
- **API State**: Fixed missing `app.state.api_key` and other required state variables
- **Signal Connections**: Prevented duplicate Qt signal connections causing multiple dialog boxes

### Added
- **Diagnostic Tool**: Added `diagnose_pairing.py` for comprehensive pairing troubleshooting
- **Enhanced Logging**: Added detailed logging throughout pairing process for debugging
- **Connection Prevention**: Added `_signals_connected` flag to prevent duplicate signal connections
- **Duplicate Protection**: Added pairing ID validation to prevent duplicate request processing
- **Certificate Validation**: Added post-generation certificate validation and fingerprint verification
- **Signal Disconnection**: Added `disconnect_signals()` method for proper cleanup

### Improved
- **Certificate Generation**: Enhanced with proper IP address formatting, validation, and cleanup on failure
- **API Endpoints**: Improved `/qr-payload` and `/pairing/request` with comprehensive error handling
- **Error Messages**: More specific error messages for certificate, network, and validation failures
- **State Management**: Proper initialization of all FastAPI app state variables
- **Logging Coverage**: Added debug, info, warning, and error logging throughout certificate and pairing processes
- **Timeout Handling**: Better handling of pairing request timeouts and user response validation

### Technical Details
- **Controller**: Added `_signals_connected` flag and `disconnect_signals()` method
- **API Server**: Enhanced error handling in `get_qr_payload()` and `request_pairing()` endpoints
- **Certificate Utils**: Improved `generate_self_signed_cert()` and `get_cert_fingerprint()` functions
- **State Initialization**: Fixed app state variables: `api_key`, `host_ip`, `host_port`, `is_https_enabled`
- **HeadlessApp**: Removed redundant `connect_signals()` call to prevent duplicate connections
- **Pairing Handler**: Added duplicate request prevention using pairing ID tracking

### Files Modified
- `src/pclink/core/controller.py`: Signal connection management and pairing dialog handling
- `src/pclink/api_server/api.py`: Enhanced API endpoint error handling and validation
- `src/pclink/core/utils.py`: Improved certificate generation and fingerprint calculation
- `src/pclink/main.py`: Fixed HeadlessApp signal connection duplication
## [1.0.1] - 2025-07-26

- startup fix
- added log option to menu
## [1.0.0] - 2025-07-24

### Added
- Initial release
- Remote PC control functionality
- File management capabilities
- Terminal access
- Process management
- QR code connection
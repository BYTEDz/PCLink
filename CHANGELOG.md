# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2025-12-26

## ✨ New Features
- **Wayland Support:** Added native Wayland compatibility. Screenshot and clipboard features now rely on `xdg-desktop-portal`, `wl-clipboard`, `grim`, or `gnome-screenshot`, depending on the desktop environment.
- **Transfer Management Dashboard:** Introduced a new Web UI section to monitor and manage file transfer sessions:
  - View stale uploads and downloads
  - Manually trigger cleanups
  - Configure automatic cleanup thresholds (default: 7 days)
- **Automated PyPI Publishing:** Added CI/CD workflows to automatically publish stable releases to PyPI.

## ⚡ Improvements
- **Smart Media Detection (Windows):**
  - Media controller now validates active audio sessions via `pycaw`, preventing silent browser tabs from being marked as playing.
  - Improved media metadata normalization for Netflix, Disney+, Apple Music, and YouTube Music.
- **Linux Distribution Enhancements:**
  - **Fedora / RPM:** Post-install script now installs recommended dependencies automatically via `dnf` (e.g. `wl-clipboard`, `python3-devel`).
  - **System Tray:** Added support for `AyatanaAppIndicator3` to ensure tray compatibility on modern Fedora and Arch-based systems.
  - **Theme Detection:** Improved dark mode detection on GNOME 42+ using the `color-scheme` setting.
- **Packaging Improvements:** Migrated to NFPM-based packaging with proper LF normalization for systemd and sudoers files, reducing installation issues on some distributions.
- **Web UI:** Added auto-scroll for logs and improved visual feedback for the auto-refresh toggle.

## 🐛 Bug Fixes
- Fixed missing platform and version information in the device management list.
- Resolved Linux errors caused by CRLF line endings in configuration scripts.
- Fixed log auto-scroll behavior to keep the view pinned to the latest entries.

## 🧰 Internal / Technical
- Improved API `AnnouncePayload` accuracy for client version and device ID tracking.
- Refactored `system_tray.py` to improve fallback behavior when GTK libraries are unavailable.
- Centralized Wayland detection logic in `wayland_utils.py`.

## [3.0.0] - 2025-12-07

# PCLink 3.0.0 — Codename “Blaze”

## API & Core Improvements
• Centralized media logic into `services.py` with a unified cross-platform media dictionary.  
• Added sticky caching to prevent “Nothing Playing” flicker and provide instant UI updates.  
• Intelligent switching between Modern SMTC and legacy keyboard controls.  
• Strict timeouts added to subprocess calls to avoid system hangs.  
• Improved transfer session restoration and atomic file operations.  
• Optimized concurrent chunk uploads with chunk-specific locks and backward compatibility.  
• Enhanced debugging with detailed offset logging.  
• Added tags to API routers for clearer OpenAPI structure.

## File Transfers
• Added `/pause/{upload_id}` endpoint to pause active uploads.  
• Improved behavior when clients disconnect during uploads.  
• Restores interrupted upload sessions on startup.  
• Transfer routers now register before file browser routes for predictable behavior.

## Input & Mouse Control
• Added full mouse control API (move, click, scroll).  
• Implemented 60Hz rate limiting for smoother and lighter input handling.  
• Fixed double-click support and click count logic.

## Performance Enhancements
• Broadcaster now pauses heavy system polling when no clients are connected.  
• Added a 2-second media info cache to reduce subprocess calls.  
• Optimized Windows terminal session loop by increasing sleep interval.

## Platform Improvements
### Windows
• Integrated `WindowsSelectorEventLoopPolicy` for improved asyncio stability.  
• Fixed COM threading issues affecting volume control.  
• Improved error handling for registry-based theme detection.

### Linux
• Better systemd user service generation for headless systems.  
• Injected required environment variables (`XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`) for stability.  
• Removed outdated Linux auto-start detection script.

## CLI Enhancements
• Added `setup` command for first-time password configuration.  
• Added `pair` command to display pairing data and QR codes (with text fallback).  
• Added safe fallback for the `qr` command in non-TTY environments.  
• Updated CLI entry point to `pclink.__main__:cli`.

## Web UI
• Added a “Guide” tab with quick-start CLI commands and copy-to-clipboard actions.  
• Overhauled update banner with new UI, gradient styling, markdown release notes, and interactive controls.  
• Added “Show/Hide Notes,” “Dismiss,” and “View Full Release” actions.

## Auto-Start & Settings
• Implemented native OS-level auto-start handling.  
• Synced stored config with actual OS startup settings.  
• Improved platform handling around auto-start visibility.

## Security
• API key is now generated and stored only after setup is fully completed.

## Documentation
• Updated README and platform notes to reflect Windows 10+ requirements.

## [2.6.0] - 2025-11-23

This release introduces a significant architectural overhaul, replacing the legacy headless mode with a robust CLI-based controller and improved service management. It brings rich media control support for Windows (SMTC), media streaming capabilities, and enhanced security measures including rate limiting. Installation on Linux has been heavily improved with new rescue scripts and robust package manager hooks.

New Features
- CLI Interface: Completely rewrote the entry point using click. New commands include start, stop, restart, status, logs, and qr for terminal-based management.
- Media Streaming: Added a new API endpoint (/files/stream) supporting HTTP Range requests for streaming video and audio content.
- Rich Media Control (Windows): Implemented winsdk and pycaw integration to support System Media Transport Controls (SMTC), enabling retrieval of metadata (Title, Artist, Album, Timeline) and advanced playback control.
- Security Policy: Added SECURITY.md and implemented rate limiting for Web UI login attempts to prevent brute-force attacks.
- Pre-Install Safety: Introduced pre-install-pclink.sh to detect and clean broken installations or orphaned files before upgrading.

Bug Fixes
- Linux Package Scripts: Removed set -e from postinst, prerm, and postrm scripts to prevent package manager corruption during non-fatal errors.
- IP Detection: Improved get_available_ips to filter out virtual interfaces (Docker, VMnet, veth) for more accurate QR code generation.
- Timing Attacks: Switched to secrets.compare_digest for API key string comparison to prevent timing attacks.
- Windows Drive Detection: Switched to Windows API for faster and safer logical drive detection in the file browser.

Improvements
- Async I/O: Integrated aiofiles for optimized asynchronous file writing and streaming.
- Startup Management: Completely rewritten startup logic using Task Scheduler (Windows) and Systemd (Linux) for higher reliability compared to registry/desktop entries.
- Rescue Script: Updated force-purge-pclink.sh to v2.5.0 with comprehensive cleanup capabilities for locking issues and corrupt dpkg states.
- ZIP Handling: Optimized file compression and extraction with reduced system calls and better progress reporting.
- Assets: Updated branding with new SVG assets and favicon handling.

Refactors
- Architecture: Removed HeadlessApp in favor of a centralized ServerController and SystemTrayManager.
- Dependency Management: Removed requirements.txt files; dependencies are now managed centrally in pyproject.toml.
- API Key Storage: Migrated legacy .env or api_key.txt storage to a hidden .api_key file.
- Documentation: Moved extensive documentation from the repo to the GitHub Wiki; cleaned up docs/ directory.

DevOps / Config
- Build System: Added support for building Python Wheels (build-wheel job) in the CI pipeline.
- Dependencies: Added procps to Linux package dependencies and winsdk/pycaw for Windows.
- Config: Added allow_terminal_access configuration option (defaulting to False).

## [2.5.0] - 2025-11-16

PCLink v2.5.0 “Astra” – Major Cross-Platform Upgrade

This release delivers significant improvements across the entire PCLink ecosystem: new automation tools, stronger media and application APIs, expanded system control, major I/O upgrades, ZIP archive features, and broad refactoring for reliability and maintainability.

New Features
-----------
Application System:
• Linux application discovery via .desktop file scanning
• Cross-platform application support (Windows + Linux)
• New /applications/icon endpoint for serving app icons
• Windows discovery now includes executable path for icon extraction

Macros:
• Added macro support and integrated macro_router under /macro

Archive Management:
• ZIP compression and extraction (with password support)
• Detect if a ZIP archive is encrypted
• Live progress updates using SSE

File Transfers:
• Fully resumable uploads/downloads
• Sessions persisted to disk for recovery on server restart
• Pause, resume, cancel actions available via client notifications

File Browser:
• Thumbnail generation and caching for image files

System Control & Automation:
• Remote command execution via POST /command
• Corrected Windows shutdown/reboot logic
• Added Hybrid Shutdown/Reboot support

System Monitoring:
• Disk usage reporting for all partitions
• Expanded metrics: uptime, CPU usage/frequency, RAM/swap, basic sensor data

Tray Icon:
• Auto light/dark theme detection and adaptive tray icons

Improvements
-----------
Media API:
• Fully redesigned /media endpoint
• Clear playback states: playing, paused, no_session
• Shuffle/repeat mode reporting
• Structured model and server timestamp included

Input Handling:
• Platform-aware key translation via _map_platform_key
• /keyboard now correctly handles main and modifier keys per OS

I/O Performance:
• All blocking file I/O moved to asyncio.to_thread
• Uploads optimized with 256KB chunks and 1MB buffer using aiofiles
• Download stream size increased from 32KB to 64KB

App Server:
• Integrated applications_router under /applications
• Mobile API activation enforced for pairing via dependency

Debugging:
• /debug-info now displays both in-memory and persisted transfer sessions

Refactors
---------
Media System:
• Major cleanup and simplification
• Strongly-typed Pydantic models for responses
• Unified platform-specific media control logic

General Cleanup:
• Removed unused comments and docstrings across api.py, input_router.py, system_router.py, utils_router.py

Bug Fixes
---------
• Screenshot endpoint now correctly returns image data
• Fixed incorrect Windows shutdown hybrid flag
• Simplified and corrected Windows reboot command
• Resolved keyboard mapping inconsistencies using OS detection

DevOps / Config
---------------
• Added Pillow dependency for thumbnail generation
• Added modules needed for remote command execution and OS handling

Additional Enhancements
-----------------------
• Added a direct upload endpoint for maximum speed
• Added conflict resolution (abort / overwrite / keep both)
• Maintains full backward compatibility
• Async file I/O with graceful fallback logic

## [2.4.0] - 2025-10-17

- No changes documented
## [2.3.0] - 2025-10-16

## Bug Fixes

-   Fix: QR code rendering to ensure scannability, especially with dark mode browser extensions.
-   Fix: Replaced incorrect and outdated UI icons (`qr-code`, `rotate-cw`, etc.) for better clarity.
-   Fix: Resolved a potential JavaScript error when updating the last device activity status on the UI.
-   Fix: Corrected the asset path for the pairing request notification icon.

## Enhancements

-   Feature: Added a "Regenerate" button to allow users to create a new pairing QR code.
-   Feature: Added a "Manual Entry Data" modal to provide a fallback for users who cannot scan the QR code.
-   Enhance: The pairing QR code payload now includes the server's certificate fingerprint to improve connection security.
-   Enhance: The pairing page UI has been improved with clearer instructions, scanning tips, and visible connection details.
-   Enhance: QR code and icon libraries are now served locally, removing CDN dependency and improving offline reliability.
## [2.2.0] - 2025-10-15

## Bug Fixes

-   Fix: WebUI now correctly handles WebSocket disconnections and attempts to reconnect.
-   Fix: WebUI WebSocket connection now uses the `/ws/ui` endpoint with cookie-based authentication.
-   Fix: Removed Qt specific logic.
-   Fix: WebUI pairing request notification.
-   Fix: Removed API Key from wsUrl.
-   Fix: Ensure 'mobile_api_enabled' setting in server status.
-   Fix: Correct WebUI port display.

## Enhancements

-   Feature: Secure mode enabled after setup password creation.
-   Enhance: Mobile API and discovery only activate after initial password setup.
-   Enhance: Clearer headless startup messages.
-   Refactor: Removed legacy Qt callbacks
-   Refactor: The `HeadlessApp` now directly uses the `Controller` for server management.
-   Refactor: Restructured headless mode and startup sequence.
-   Refactor: Removed controller reference from `api.py`.
-   Refactor: Enhanced headless mode to use web-ui and system tray.
-   Refactor: Removed legacy qt code.
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
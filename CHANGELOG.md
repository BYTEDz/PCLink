# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]


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
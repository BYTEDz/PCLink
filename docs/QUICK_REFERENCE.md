# PCLink Quick Reference

## Project Structure Overview

```
src/pclink/
├── __main__.py, main.py, launcher.py    # Entry points
├── api_server/                          # FastAPI REST API
│   ├── api.py                          # Main routes & auth
│   ├── discovery.py                    # Device pairing
│   ├── file_browser.py                 # File operations
│   ├── process_manager.py              # Process control
│   └── terminal.py                     # Shell access
├── core/                               # Business logic
│   ├── controller.py                   # Main orchestrator
│   ├── state.py                        # Global state + signals
│   ├── device_manager.py               # Connection tracking
│   ├── constants.py                    # App configuration
│   └── utils.py, security.py, etc.    # Utilities
├── gui/                                # PySide6 interface
│   ├── main_window.py                  # Primary window
│   ├── layout.py                       # UI setup
│   └── theme.py, localizations.py     # Styling & i18n
└── assets/                             # Icons & resources
```

## Key Components

### Application Modes
- **GUI Mode**: Full Qt interface (`MainWindow`)
- **Headless Mode**: Background server (`HeadlessApp`)
- **Unified Tray**: Consistent system tray across modes

### Core Flow
1. **Entry Point** → `main.py` determines GUI vs headless mode
2. **Controller** → `controller.py` orchestrates server and UI
3. **API Server** → FastAPI handles mobile app requests
4. **State Management** → `state.py` tracks devices with Qt signals
5. **GUI Updates** → Real-time UI updates via signal/slot pattern

### Key Files to Understand
- **`main.py`**: Application startup and mode selection
- **`controller.py`**: Central business logic coordinator
- **`api.py`**: Main API routes and authentication
- **`state.py`**: Thread-safe device state with GUI signals
- **`main_window.py`**: Primary user interface

## Development Commands

```bash
# Run application
python -m pclink                    # Module mode
python src/pclink/main.py          # Direct execution
python -m pclink --startup         # Headless mode

# Build executable
python scripts/build.py            # PyInstaller build
python scripts/build.py --debug    # Debug build

# Testing
pytest                              # Run test suite
```

## Architecture Patterns

- **MVC**: Model (`state.py`) + View (`gui/`) + Controller (`controller.py`)
- **Singleton**: Single app instance with system-wide locking
- **Observer**: Qt signals for loose coupling between components
- **Factory**: Dynamic API app and dialog creation
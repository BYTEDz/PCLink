# PCLink Quick Reference

## 📂 Project Structure

```

src/pclink/
├── **main**.py, main.py, launcher.py    # Entry points
├── api\_server/                          # FastAPI REST API
│   ├── api.py                          # Main routes & auth
│   ├── discovery.py                    # Device pairing
│   ├── file\_browser.py                 # File operations
│   ├── process\_manager.py              # Process control
│   └── terminal.py                     # Shell access
├── core/                               # Business logic
│   ├── controller.py                   # Main orchestrator
│   ├── state.py                        # Global state + signals
│   ├── device\_manager.py               # Connection tracking
│   ├── constants.py                    # App configuration
│   └── utils.py, etc.                # Utilities
├── web_ui/                             # Web interface
│   ├── main\_window\.py                  # Primary window
│   ├── layout.py                       # UI setup
│   └── theme.py, localizations.py     # Styling & i18n
├── assets/                             # Icons & resources
└── scripts/                            # Build & release automation
├── build.py
└── release.py

````

## 🧩 Key Components

### Application Modes
- **GUI Mode** → Full Qt interface (`MainWindow`)
- **Headless Mode** → Background server (`HeadlessApp`)
- **Unified Tray** → System tray integration across modes

### Core Flow
1. **Entry Point** → `main.py` starts web-first application
2. **Controller** → `controller.py` orchestrates server & UI
3. **API Server** → FastAPI handles mobile requests
4. **State** → `state.py` manages devices with Qt signals
5. **UI** → Real-time updates via signal/slot pattern

### Essential Files
- `main.py` → Startup and mode selection
- `controller.py` → Central coordinator
- `api.py` → REST API and authentication
- `state.py` → Thread-safe device state
- `main_window.py` → GUI entry point

## 🛠️ Development Commands

```bash
# Run application
python -m pclink                  # Module mode
python src/pclink/main.py         # Direct execution
python -m pclink --startup        # Headless mode

# Build executables
python scripts/build.py           # Production build
python scripts/build.py --debug   # Debug build

# Run tests
pytest                            # Full suite
pytest tests/unit/                # Unit tests only
pytest tests/integration/         # Integration tests
````

## 🏛️ Architecture Patterns

* **MVC** → Model (`state.py`), View (`web_ui/`), Controller (`controller.py`)
* **Singleton** → Ensures one app instance system-wide
* **Observer** → Callback system for decoupled updates
* **Factory** → Dynamic API apps & dialogs
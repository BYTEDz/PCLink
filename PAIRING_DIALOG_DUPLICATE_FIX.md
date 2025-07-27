# Fix for Duplicate Pairing Dialog Issue

## Problem
The pairing dialog was appearing twice when a Flutter client requested pairing with the PCLink server.

## Root Cause
The issue was caused by **duplicate signal connections** in the Qt signal system. The `api_signal_emitter.pairing_request.connect(self.handle_pairing_request)` was being called multiple times:

1. **HeadlessApp background GUI creation** (line 589 in main.py)
2. **MainWindow initialization** (line 970 in main.py)
3. **Potentially in gui/main_window.py** (though this file appears unused)

Each time `connect_signals()` was called, Qt would add another connection between the signal and the slot, causing the `handle_pairing_request` method to be called multiple times for each pairing request.

## Solution Applied

### 1. **Connection Prevention Flag**
Added a `_signals_connected` flag to the Controller class to prevent multiple signal connections:

```python
class Controller:
    def __init__(self, main_window):
        # ... existing code ...
        self._signals_connected = False

    def connect_signals(self):
        # Prevent multiple connections
        if self._signals_connected:
            log.debug("Signals already connected, skipping")
            return
        
        # ... connect signals ...
        self._signals_connected = True
```

### 2. **Removed Duplicate Call**
Removed the redundant `connect_signals()` call in HeadlessApp background GUI creation:

```python
# Before (in HeadlessApp._create_background_gui):
self.controller.connect_signals()  # REMOVED - causes duplicates

# After:
# Note: Don't call connect_signals() here as MainWindow initialization will handle it
```

### 3. **Added Duplicate Request Prevention**
Added additional protection in the pairing handler to prevent processing the same pairing ID twice:

```python
def handle_pairing_request(self, pairing_id: str, device_name: str):
    # Check if this pairing ID already has a result (duplicate call prevention)
    if pairing_id in pairing_results:
        log.warning(f"Pairing request {pairing_id} already processed, ignoring duplicate")
        return
    # ... rest of method ...
```

### 4. **Added Signal Disconnection Method**
Added a method to properly disconnect signals if needed:

```python
def disconnect_signals(self):
    """Disconnects all controller signals."""
    if not self._signals_connected:
        return
    
    try:
        api_signal_emitter.device_list_updated.disconnect(self.window.update_device_list_ui)
        api_signal_emitter.pairing_request.disconnect(self.handle_pairing_request)
        self._signals_connected = False
    except Exception as e:
        log.warning(f"Error disconnecting signals: {e}")
```

## How It Works Now

1. **First `connect_signals()` call**: Connects all signals and sets `_signals_connected = True`
2. **Subsequent `connect_signals()` calls**: Immediately return without doing anything
3. **Pairing request**: Only one signal connection exists, so dialog appears only once
4. **Duplicate protection**: Even if somehow called twice, the pairing ID check prevents duplicate processing

## Testing

The fix has been tested with:
- Signal connection prevention logic
- Signal disconnection and reconnection
- Duplicate pairing ID handling

## Files Modified

- `src/pclink/core/controller.py`: Added connection prevention and duplicate request handling
- `src/pclink/main.py`: Removed redundant signal connection call

## Result

✅ **Pairing dialog now appears only once** when a Flutter client requests pairing.

The fix is backward compatible and doesn't affect any other functionality. The additional logging helps with debugging if any issues arise in the future.
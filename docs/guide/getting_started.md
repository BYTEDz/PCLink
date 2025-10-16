# Getting Started with PCLink

This guide will help you get started with PCLink.

## Installation

### From PyPI

```bash
pip install pclink
```

### From Source

See the main [README.md](../../README.md#-building-deb-packages) for build instructions.

## Basic Usage

### Running the Application

```bash
# Run as a module (recommended)
python -m pclink

# Use the launcher script
python run_pclink.py
```

### Using as a Library

```python
from pclink import main

# Start the PCLink application
main.main()
```

## Configuration

PCLink can be configured through the GUI or by editing the configuration files directly.

### Configuration Files

- API Key: `~/.pclink/api_key.txt`
- Port: `~/.pclink/port.txt`

## Command Line Options

```
python -m pclink --startup  # Start in headless mode
```
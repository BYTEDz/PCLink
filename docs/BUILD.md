# 🏗️ Building PCLink

This guide explains how to build **PCLink** from source for development and production.

## 📋 Prerequisites

- **Python** 3.8+
- **pip** package manager
- **Git** (for development)
- Recommended: **virtualenv**

## ⚙️ Development Setup

```bash
# Clone the repository
git clone https://github.com/BYTEDz/PCLink.git
cd pclink

# Create a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# Linux
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
````

## 🏗️ Building the Package

```bash
# Development Build
python -m build --wheel

# Production Build (Recommended)
python scripts/build.py
```

### Optional: Wrapper Script

```bash
# Create wrapper script (gitignored)
echo "#!/usr/bin/env python3
import sys
from scripts.build import main
if __name__ == '__main__':
    sys.exit(main())" > build.py

# Make it executable (Linux/macOS)
chmod +x build.py

# Run
python build.py
```

## 🧪 Running Tests

```bash
pytest tests/
```

## 🚀 Creating a Release

```bash
# Run release script
python scripts/release.py

# Optional: Wrapper Script
echo "#!/usr/bin/env python3
import sys
from scripts.release import main
if __name__ == '__main__':
    sys.exit(main())" > release.py

# Make it executable (Linux/macOS)
chmod +x release.py

# Run
python release.py
```

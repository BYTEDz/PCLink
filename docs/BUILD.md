# Building PCLink

This document provides instructions for building PCLink from source.

## Prerequisites

- Python 3.8 or higher
- pip package manager
- Git (for development)

## Development Setup

1. Clone the repository:
```bash
git clone https://github.com/bYTEDz/pclink.git
cd pclink
```

2. Create a virtual environment:
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Unix/macOS:
source venv/bin/activate
```

3. Install development dependencies:
```bash
pip install -e ".[dev]"
```

4. Install pre-commit hooks:
```bash
pre-commit install
```

## Building the Package

### Development Build
```bash
python -m build --wheel
```

### Production Build

You can run the build script directly:
```bash
python scripts/build.py
```

Or create a local wrapper script for convenience:
```bash
# Create local wrapper script (this is gitignored)
echo "#!/usr/bin/env python3
import sys
from scripts.build import main
if __name__ == '__main__':
    sys.exit(main())" > build.py

# Make it executable (Linux/macOS)
chmod +x build.py

# Then use it:
python build.py
```

## Running Tests

```bash
pytest tests/
```

## Creating a Release

You can run the release script directly:
```bash
python scripts/release.py
```

Or create a local wrapper script for convenience:
```bash
# Create local wrapper script (this is gitignored)
echo "#!/usr/bin/env python3
import sys
from scripts.release import main
if __name__ == '__main__':
    sys.exit(main())" > release.py

# Make it executable (Linux/macOS)
chmod +x release.py

# Then use it:
python release.py
```
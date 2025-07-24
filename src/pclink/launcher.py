#!/usr/bin/env python3
"""
PCLink Standalone Launcher

This script is used to launch PCLink when packaged as a standalone application.
It handles the necessary imports and starts the application.
"""

import sys
import os

# Add the parent directory to sys.path if needed
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import and run the main function
from pclink.main import main

if __name__ == "__main__":
    sys.exit(main())
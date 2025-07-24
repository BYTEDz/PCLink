"""Entry point for running PCLink as a module."""

import sys

if __name__ == "__main__":
    try:
        # Try relative import first (when run as part of a package)
        from .main import main
    except ImportError:
        # Fall back to absolute import (when run directly)
        import os
        # Add the parent directory to sys.path if needed
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from pclink.main import main
    
    sys.exit(main())
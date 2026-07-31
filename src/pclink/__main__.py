# filepath: src/pclink/__main__.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys
import multiprocessing
from .cli import cli

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(cli())

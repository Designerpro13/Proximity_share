#!/usr/bin/env python3
"""
Proximity Share — peer-to-peer file sharing for personal devices.

Usage:
    python main.py            Run the desktop GUI application
    python -m src             Same, via package entry point
"""

import sys
from pathlib import Path

# Add src/ to import path so modules use bare names (e.g. `from core.app import ...`)
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.app import ProximityShareApp


def main():
    app = ProximityShareApp()
    app.run()


if __name__ == "__main__":
    main()

"""Allow running as: python -m src"""

import sys
from pathlib import Path

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).parent))

from core.app import ProximityShareApp


def main():
    ProximityShareApp().run()


if __name__ == "__main__":
    main()

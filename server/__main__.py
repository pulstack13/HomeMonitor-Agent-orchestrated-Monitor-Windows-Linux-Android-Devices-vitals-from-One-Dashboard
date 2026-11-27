"""Run the HomeMonitor central server.

Usage:
    python -m server --data-dir ./data --port 8787
"""

from .controller.server import main

if __name__ == "__main__":
    raise SystemExit(main())

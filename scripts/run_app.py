"""Convenience launcher for the Streamlit dashboard.

    python -m scripts.run_app
"""
from __future__ import annotations

import sys
from pathlib import Path

from streamlit.web import cli as stcli


def main() -> None:
    app = Path(__file__).resolve().parent.parent / "app.py"
    sys.argv = ["streamlit", "run", str(app), "--server.port=8501", "--server.headless=true"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()

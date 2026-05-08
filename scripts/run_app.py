"""Convenience launcher for the NiceGUI dashboard.

    python -m scripts.run_app
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vaultiq.ui.nicegui_app import main  # noqa: E402


if __name__ in {"__main__", "__mp_main__"}:
    main()

"""VaultIQ NiceGUI entry point — run from the repo root.

    python app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vaultiq.ui.nicegui_app import main  # noqa: E402

if __name__ in {"__main__", "__mp_main__"}:
    main()

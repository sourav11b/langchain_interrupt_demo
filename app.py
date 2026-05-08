"""VaultIQ Streamlit entry point — run from the repo root.

    streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Re-export the dashboard module so Streamlit executes its top-level code.
import src.vaultiq.ui.streamlit_app  # noqa: F401,E402

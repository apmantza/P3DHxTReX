"""Refresh every derived table after a download: load, clean, classify.

  build_p3dh_db.py     loads new or changed CSV files (incremental)
  clean_p3dh.py        tests units and dates, writes clean_period_fact and dq_flag
  classify_p3dh.py     writes the geography and size classes
  clean_templates.py   cleans IRRBB1 and encumbrance (AE1 to AE3), writes the template status note

The four steps run in order. The script stops at the first step that fails.

  PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/refresh_p3dh.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
STEPS = ("build_p3dh_db.py", "clean_p3dh.py", "classify_p3dh.py", "clean_templates.py")


def main() -> int:
    for name in STEPS:
        print(f"\n===== {name} =====", flush=True)
        code = subprocess.call([sys.executable, str(SCRIPTS / name)])
        if code:
            print(f"{name} failed with exit code {code}. The later steps did not run.", file=sys.stderr)
            return code
    print("\nAll steps finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

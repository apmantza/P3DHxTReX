from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_step(args: list[str], label: str) -> None:
    print(f"\n== {label} ==")
    completed = subprocess.run(args, cwd=REPO_ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    python = str(REPO_ROOT / ".venv" / "Scripts" / "python")
    run_step([python, "scripts/download_via_api.py"], "Download P3DH via API")
    run_step([python, "scripts/ingest_raw.py"], "Ingest raw data")


if __name__ == "__main__":
    main()

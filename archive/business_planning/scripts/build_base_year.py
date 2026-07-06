from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

import pandas as pd

from modules.ingestion.base_year import export_base_year, find_bank_names


def main() -> None:
    peerdata_path = repo_root / "data" / "processed" / "peerdata.csv"
    output_dir = repo_root / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    institutions_path = output_dir / "trex_institutions.csv"

    target_bank = "National Bank of Greece"
    try:
        base_year = export_base_year(
            peerdata_path,
            target_bank,
            output_dir / "base_year_nbg.csv",
            institutions_path=institutions_path,
        )
        print(f"Base year exported: {len(base_year.index)} rows")
    except ValueError as exc:
        print(str(exc))
        names = find_bank_names(
            pd.read_csv(peerdata_path, encoding="utf-8-sig"),
            target_bank,
        )
        if names:
            print("Closest matches:")
            for name in names[:10]:
                print(f"- {name}")


if __name__ == "__main__":
    main()

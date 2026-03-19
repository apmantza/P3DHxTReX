from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from modules.ingestion.base_year_views import export_base_year_wide, export_base_year_enriched


def main() -> None:
    base_year_path = repo_root / "data" / "processed" / "base_year_nbg.csv"
    
    wide_path = repo_root / "data" / "processed" / "base_year_nbg_wide.csv"
    wide = export_base_year_wide(base_year_path, wide_path)
    print(f"Base year wide exported: {len(wide.columns) - 1} metrics")

    enriched_path = repo_root / "data" / "processed" / "base_year_nbg_enriched.csv"
    enriched = export_base_year_enriched(base_year_path, enriched_path)
    print(f"Base year enriched exported: {len(enriched.index)} rows with YoY%, QoQ%, normalizations")


if __name__ == "__main__":
    main()

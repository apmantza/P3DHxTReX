"""
Rate assumptions loader for business planning.
Loads user-defined forward rate assumptions from CSV.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import pandas as pd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


VALID_RATES = {"ESTER", "EURIBOR_1M", "EURIBOR_3M", "EURIBOR_6M", "EURIBOR_1Y", "MRO", "DFR"}
VALID_SCENARIOS = {"base", "upside", "downside", "stress"}


def create_template(output_path: Path) -> None:
    """Create a template CSV for rate assumptions."""
    template_data = []
    for rate in sorted(VALID_RATES):
        for year in [2025, 2026, 2027, 2028, 2029]:
            for quarter in [1, 2, 3, 4]:
                for scenario in ["base", "upside", "downside"]:
                    template_data.append({
                        "rate": rate,
                        "year": year,
                        "quarter": quarter,
                        "scenario": scenario,
                        "value": "",
                    })

    df = pd.DataFrame(template_data)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Template created: {output_path}")


def load_assumptions(csv_path: Path, db_path: Path) -> int:
    """Load rate assumptions from CSV into DB."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    df["rate"] = df["rate"].str.strip().str.upper()
    df["scenario"] = df["scenario"].str.strip().str.lower()

    invalid_rates = df[~df["rate"].isin(VALID_RATES)]["rate"].unique()
    if len(invalid_rates) > 0:
        raise ValueError(f"Invalid rates: {invalid_rates}. Valid: {VALID_RATES}")

    invalid_scenarios = df[~df["scenario"].isin(VALID_SCENARIOS)]["scenario"].unique()
    if len(invalid_scenarios) > 0:
        raise ValueError(f"Invalid scenarios: {invalid_scenarios}. Valid: {VALID_SCENARIOS}")

    df = df[df["value"].notna() & (df["value"] != "")]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[df["value"].notna()]

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_assumptions (
                id INTEGER PRIMARY KEY,
                rate VARCHAR NOT NULL,
                year INTEGER NOT NULL,
                quarter INTEGER NOT NULL,
                scenario VARCHAR NOT NULL,
                value REAL NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(rate, year, quarter, scenario)
            )
        """)

        records = list(df[["rate", "year", "quarter", "scenario", "value"]].itertuples(index=False, name=None))

        conn.executemany(
            """
            INSERT OR REPLACE INTO rate_assumptions (rate, year, quarter, scenario, value)
            VALUES (?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
        return len(records)
    finally:
        conn.close()


def main() -> None:
    processed_dir = repo_root / "data" / "processed"
    db_path = processed_dir / "bbirr.db"
    template_path = processed_dir / "rate_assumptions_template.csv"
    input_path = processed_dir / "rate_assumptions.csv"

    if not input_path.exists():
        create_template(template_path)
        print(f"\nPlease fill in {input_path} (copy from template) and re-run.")
        return

    inserted = load_assumptions(input_path, db_path)
    print(f"Loaded {inserted} rate assumptions")

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT scenario, rate, COUNT(*) as cnt
        FROM rate_assumptions
        GROUP BY scenario, rate
        ORDER BY scenario, rate
    """)
    print("\nLoaded assumptions:")
    for row in cursor.fetchall():
        print(f"  {row[0]:8} {row[1]:12} {row[2]} periods")
    conn.close()


if __name__ == "__main__":
    main()

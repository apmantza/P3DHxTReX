from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import pandas as pd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


SERIES_MAP = {
    "ESTER": ("ESTER", None),
    "EURIBOR_1M": ("EURIBOR", "1M"),
    "EURIBOR_3M": ("EURIBOR", "3M"),
    "EURIBOR_6M": ("EURIBOR", "6M"),
    "EURIBOR_1Y": ("EURIBOR", "1Y"),
    "MRO": ("MRO", None),
    "DFR": ("DFR", None),
}


def main() -> None:
    db_path = repo_root / "data" / "processed" / "bbirr.db"
    rates_path = repo_root / "data" / "processed" / "ecb_rates_quarterly.csv"

    df = pd.read_csv(rates_path, encoding="utf-8-sig")
    df["quarter"] = pd.to_datetime(df["quarter"])

    records = []
    for _, row in df.iterrows():
        rate_name = row["rate_name"]
        if rate_name not in SERIES_MAP:
            continue
        series, tenor = SERIES_MAP[rate_name]
        records.append((
            row["quarter"].date(),
            series,
            tenor,
            row["value"],
            None,  # country (EU-wide)
            "ECB_SDW",
        ))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            DROP INDEX IF EXISTS uq_historical_rate_curves
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX uq_historical_rate_curves
            ON historical_rate_curves (date, series, tenor, country)
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO historical_rate_curves
            (date, series, tenor, rate, country, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
        print(f"Inserted {len(records)} rate records into historical_rate_curves")

        # Show summary
        cursor = conn.execute(
            """
            SELECT series, tenor, COUNT(*) as cnt
            FROM historical_rate_curves
            GROUP BY series, tenor
            ORDER BY series, tenor
            """
        )
        print("\nStored rates:")
        for row in cursor.fetchall():
            print(f"  {row[0]} ({row[1]}): {row[2]} quarters")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

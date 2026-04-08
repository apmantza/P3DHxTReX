from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import pandas as pd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


RATE_MAP = {
    "SPOT_1Y":  ("YIELD_CURVE_SPOT", "1Y"),
    "SPOT_2Y":  ("YIELD_CURVE_SPOT", "2Y"),
    "SPOT_5Y":  ("YIELD_CURVE_SPOT", "5Y"),
    "SPOT_10Y": ("YIELD_CURVE_SPOT", "10Y"),
    "SPOT_15Y": ("YIELD_CURVE_SPOT", "15Y"),
    "SPOT_20Y": ("YIELD_CURVE_SPOT", "20Y"),
    "SPOT_30Y": ("YIELD_CURVE_SPOT", "30Y"),
    "FWD_1Y":   ("YIELD_CURVE_FWD",  "1Y"),
    "FWD_5Y":   ("YIELD_CURVE_FWD",  "5Y"),
    "FWD_10Y":  ("YIELD_CURVE_FWD",  "10Y"),
    "FWD_15Y":  ("YIELD_CURVE_FWD",  "15Y"),
    "FWD_20Y":  ("YIELD_CURVE_FWD",  "20Y"),
    "FWD_30Y":  ("YIELD_CURVE_FWD",  "30Y"),
}


def main() -> None:
    db_path = repo_root / "data" / "processed" / "bbirr.db"
    yc_path = repo_root / "data" / "processed" / "ecb_yield_curve_quarterly.csv"

    df = pd.read_csv(yc_path, encoding="utf-8-sig")
    df["quarter"] = pd.to_datetime(df["quarter"])

    records = []
    for _, row in df.iterrows():
        rate_name = row["rate_name"]
        if rate_name not in RATE_MAP:
            continue
        series, tenor = RATE_MAP[rate_name]
        records.append((
            row["quarter"].date(),
            series,
            tenor,
            row["value"],
            None,
            "ECB_SDW_YC",
        ))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_rate_curves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE,
                series TEXT,
                tenor TEXT,
                rate REAL,
                country TEXT,
                source TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_historical_rate_curves
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
        print(f"Inserted {len(records)} yield curve records into historical_rate_curves")

        cursor = conn.execute(
            """
            SELECT series, tenor, COUNT(*) as cnt
            FROM historical_rate_curves
            GROUP BY series, tenor
            ORDER BY series, tenor
            """
        )
        print("\nStored rate series:")
        for row in cursor.fetchall():
            print(f"  {row[0]} ({row[1]}): {row[2]} quarters")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
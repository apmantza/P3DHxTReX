from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import sys

import pandas as pd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from db.engine import get_engine


def build_labels(row: pd.Series) -> str | None:
    labels = {k: v for k, v in row.items() if k.endswith("_label") and pd.notna(v)}
    if not labels:
        return None
    return json.dumps(labels, ensure_ascii=False)


def main() -> None:
    db_path = repo_root / "data" / "processed" / "bbirr.db"
    base_year_path = repo_root / "data" / "processed" / "base_year_nbg.csv"

    df = pd.read_csv(base_year_path, encoding="utf-8-sig", low_memory=False)
    df["period"] = pd.to_datetime(df["period"], errors="coerce").dt.date
    df["labels_json"] = df.apply(build_labels, axis=1)

    snapshot_name = "base_year_nbg"
    df["snapshot_name"] = snapshot_name

    cols = [
        "snapshot_name",
        "bank_name",
        "bank_lei",
        "period",
        "template",
        "item",
        "column",
        "amount",
        "source",
        "labels_json",
    ]
    records = list(df[cols].itertuples(index=False, name=None))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_base_year
            ON base_year_snapshots (snapshot_name, bank_name, bank_lei, period, template, item, column)
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO base_year_snapshots
            (snapshot_name, bank_name, bank_lei, period, template, item, column, amount, source, labels_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
        print(f"Attempted {len(records)} inserts into base_year_snapshots")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

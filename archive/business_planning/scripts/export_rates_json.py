"""
Export rate assumptions to JSON for use in calculations.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


def export_rates_json(db_path: Path, output_path: Path, scenario: str = "base") -> None:
    """Export rate assumptions as JSON."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(f"""
        SELECT rate, year, quarter, value
        FROM rate_assumptions
        WHERE scenario = '{scenario}'
        ORDER BY rate, year, quarter
    """, conn)
    conn.close()

    if df.empty:
        print(f"No assumptions found for scenario '{scenario}'")
        return

    by_rate = {}
    for rate in df["rate"].unique():
        rate_data = df[df["rate"] == rate]
        by_rate[rate] = [
            {"year": r["year"], "quarter": r["quarter"], "value": r["value"]}
            for _, r in rate_data.iterrows()
        ]

    output = {
        "scenario": scenario,
        "rates": by_rate,
    }

    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Exported to {output_path}")


def get_current_rates(db_path: Path) -> dict:
    """Get latest historical rates from DB."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT series, tenor, rate, date
        FROM historical_rate_curves
        WHERE date = (SELECT MAX(date) FROM historical_rate_curves h2 WHERE h2.series = historical_rate_curves.series AND h2.tenor = historical_rate_curves.tenor)
        ORDER BY series, tenor
    """)
    rates = {}
    for row in cursor.fetchall():
        key = row[1] if row[1] else row[0]
        rates[key] = row[2]
    conn.close()
    return rates


def generate_yaml_values(db_path: Path, scenario: str = "base") -> dict:
    """Generate YAML-compatible values from rate assumptions."""
    conn = sqlite3.connect(db_path)

    df_assumptions = pd.read_sql(f"""
        SELECT rate, year, quarter, value
        FROM rate_assumptions
        WHERE scenario = '{scenario}' AND year = 2025
        ORDER BY rate, quarter
    """, conn)

    df_historical = pd.read_sql("""
        SELECT series, tenor, rate
        FROM historical_rate_curves
        WHERE date = (SELECT MAX(date) FROM historical_rate_curves)
    """, conn)
    conn.close()

    historical = {}
    for _, row in df_historical.iterrows():
        key = row["tenor"] if row["tenor"] else row["series"]
        historical[key] = row["rate"]

    assumptions = {}
    for rate in df_assumptions["rate"].unique():
        rate_data = df_assumptions[df_assumptions["rate"] == rate]
        if not rate_data.empty:
            q1_2025 = rate_data[(rate_data["year"] == 2025) & (rate_data["quarter"] == 1)]
            if not q1_2025.empty:
                assumptions[rate] = q1_2025.iloc[0]["value"] / 100

    yaml_values = {
        "current_rates": historical,
        "assumptions_2025_q1": assumptions,
    }

    return yaml_values


def main() -> None:
    processed_dir = repo_root / "data" / "processed"
    db_path = processed_dir / "bbirr.db"
    config_dir = repo_root / "config"

    current = get_current_rates(db_path)
    print("Current rates (latest in DB):")
    for k, v in current.items():
        print(f"  {k}: {v}%")

    for scenario in ["base", "upside", "downside"]:
        json_path = processed_dir / f"forward_rates_{scenario}.json"
        export_rates_json(db_path, json_path, scenario)

    yaml_values = generate_yaml_values(db_path)
    yaml_path = config_dir / "current_rates.json"
    yaml_path.write_text(json.dumps(yaml_values, indent=2), encoding="utf-8")
    print(f"\nCurrent rates JSON: {yaml_path}")


if __name__ == "__main__":
    import pandas as pd
    main()

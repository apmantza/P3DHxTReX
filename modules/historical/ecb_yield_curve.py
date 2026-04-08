"""
modules/historical/ecb_yield_curve.py — Fetch ECB euro area yield curve from SDW.

The ECB publishes daily yield curve parameters (beta0-beta3, tau) and derived
spot/forward rates via the YC dataflow. We fetch the most useful tenors for
bank stress testing and IRRBB modelling.

Series available:
  - Spot rates:   SR_1Y, SR_2Y, SR_3Y, ..., SR_30Y
  - Forward rates: IF_1Y, IF_5Y, IF_10Y, IF_15Y, IF_20Y, IF_30Y
  - Parameters:    BETA0, BETA1, BETA2, BETA3, TAU1, TAU2

We aggregate to quarterly (month-end) frequency like the other rate series.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))


YC_SERIES = {
    "SPOT_1Y": "SR_1Y",
    "SPOT_2Y": "SR_2Y",
    "SPOT_5Y": "SR_5Y",
    "SPOT_10Y": "SR_10Y",
    "SPOT_15Y": "SR_15Y",
    "SPOT_20Y": "SR_20Y",
    "SPOT_30Y": "SR_30Y",
    "FWD_1Y": "IF_1Y",
    "FWD_5Y": "IF_5Y",
    "FWD_10Y": "IF_10Y",
    "FWD_15Y": "IF_15Y",
    "FWD_20Y": "IF_20Y",
    "FWD_30Y": "IF_30Y",
}

YC_BASE_URL = "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.{maturity}"


def fetch_yield_curve(
    start: str = "2020-01",
    end: str | None = None,
) -> pd.DataFrame:
    if end is None:
        end = datetime.now().strftime("%Y-%m")

    import requests

    all_data: list[pd.DataFrame] = []

    for name, maturity in YC_SERIES.items():
        url = f"{YC_BASE_URL.format(maturity=maturity)}?format=csvdata&detail=dataonly&startPeriod={start}&endPeriod={end}"
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            df = pd.read_csv(pd.io.common.StringIO(resp.text))
            df = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
            df = df.rename(columns={"OBS_VALUE": "value"})
            df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
            df["rate_name"] = name
            all_data.append(df)
            print(f"Fetched {name}: {len(df)} rows")
        except Exception as e:
            print(f"Failed to fetch {name}: {e}")

    if not all_data:
        return pd.DataFrame()

    return pd.concat(all_data, ignore_index=True)


def aggregate_to_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    daily_df = df.set_index("TIME_PERIOD")
    q = (
        daily_df.groupby("rate_name")
        .resample("QE")
        .mean(numeric_only=True)
        .reset_index()
    )
    q = q.rename(columns={"TIME_PERIOD": "quarter"})

    return q


def main() -> None:
    raw = fetch_yield_curve()
    if raw.empty:
        print("No yield curve data fetched")
        return

    processed_dir = repo_root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    raw_path = processed_dir / "ecb_yield_curve_raw.csv"
    raw.to_csv(raw_path, index=False, encoding="utf-8-sig")
    print(f"\nRaw yield curve saved to {raw_path}")

    quarterly = aggregate_to_quarterly(raw)
    quarterly_path = processed_dir / "ecb_yield_curve_quarterly.csv"
    quarterly.to_csv(quarterly_path, index=False, encoding="utf-8-sig")
    print(f"Quarterly yield curve saved to {quarterly_path}")

    print("\nQuarterly summary:")
    for name in quarterly["rate_name"].unique():
        subset = quarterly[quarterly["rate_name"] == name]
        if not subset.empty:
            min_q = subset["quarter"].min()
            max_q = subset["quarter"].max()
            min_q_str = min_q.strftime("%Y") + "-Q" + str((min_q.month - 1) // 3 + 1)
            max_q_str = max_q.strftime("%Y") + "-Q" + str((max_q.month - 1) // 3 + 1)
            print(f"  {name}: {len(subset)} quarters, range {min_q_str} - {max_q_str}")


if __name__ == "__main__":
    main()
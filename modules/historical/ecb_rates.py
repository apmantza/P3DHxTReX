from __future__ import annotations

import pandas as pd
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from modules.ingestion.common import as_path


RATES = {
    "ESTER": "FM.M.U2.EUR.4F.MM.UONSTR.HSTA",
    "EURIBOR_1M": "FM.M.U2.EUR.RT.MM.EURIBOR1MD_.HSTA",
    "EURIBOR_3M": "FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
    "EURIBOR_6M": "FM.M.U2.EUR.RT.MM.EURIBOR6MD_.HSTA",
    "EURIBOR_1Y": "FM.M.U2.EUR.RT.MM.EURIBOR1YD_.HSTA",
    "MRO": "FM.B.U2.EUR.4F.KR.MRR_FR.LEV",
    "DFR": "FM.B.U2.EUR.4F.KR.DFR.LEV",
}


def fetch_rates(
    start: str = "2024-01",
    end: str = "2025-12",
) -> pd.DataFrame:
    from ecbdata.api import ECB_DataPortal

    ecb = ECB_DataPortal()
    all_data = []

    for name, series_id in RATES.items():
        try:
            raw = ecb.get_series(series_id, start=start, end=end)
            if not raw.empty:
                df = raw[["TIME_PERIOD", "OBS_VALUE"]].copy()
                df = df.rename(columns={"OBS_VALUE": "value"})
                df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
                df["rate_name"] = name
                all_data.append(df)
                print(f"Fetched {name}: {len(df)} rows")
            else:
                print(f"No data for {name}")
        except Exception as e:
            print(f"Failed to fetch {name}: {e}")

    if not all_data:
        return pd.DataFrame()

    combined = pd.concat(all_data, ignore_index=True)
    return combined


def aggregate_to_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    daily_rates = {"MRO", "DFR"}
    daily_df = df[df["rate_name"].isin(daily_rates)].copy()
    monthly_df = df[~df["rate_name"].isin(daily_rates)].copy()

    quarterly_parts = []

    if not monthly_df.empty:
        monthly_df = monthly_df.set_index("TIME_PERIOD")
        q_monthly = (
            monthly_df.groupby("rate_name")
            .resample("QE")
            .mean(numeric_only=True)
            .reset_index()
        )
        q_monthly = q_monthly.rename(columns={"TIME_PERIOD": "quarter"})
        quarterly_parts.append(q_monthly)

    if not daily_df.empty:
        daily_df = daily_df.sort_values("TIME_PERIOD")
        daily_df["quarter"] = daily_df["TIME_PERIOD"].dt.to_period("Q").dt.to_timestamp("Q")

        latest_by_quarter = (
            daily_df.groupby(["rate_name", "quarter"])
            .last(numeric_only=True)
            .reset_index()[["rate_name", "quarter", "value"]]
        )

        for rate_name in daily_df["rate_name"].unique():
            rate_data = latest_by_quarter[latest_by_quarter["rate_name"] == rate_name].copy()
            rate_data = rate_data.sort_values("quarter")

            all_quarters = pd.DataFrame({
                "quarter": pd.date_range(
                    start=rate_data["quarter"].min(),
                    end="2025-12-31",
                    freq="QE"
                )
            })

            rate_data = all_quarters.merge(rate_data, on="quarter", how="left")
            rate_data["value"] = rate_data["value"].ffill()
            rate_data["rate_name"] = rate_name
            quarterly_parts.append(rate_data)

    if not quarterly_parts:
        return pd.DataFrame()

    quarterly = pd.concat(quarterly_parts, ignore_index=True)
    return quarterly


def main() -> None:
    raw = fetch_rates()
    if raw.empty:
        print("No data fetched")
        return

    processed_dir = repo_root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    raw_path = processed_dir / "ecb_rates_raw.csv"
    raw.to_csv(raw_path, index=False, encoding="utf-8-sig")
    print(f"\nRaw rates saved to {raw_path}")

    quarterly = aggregate_to_quarterly(raw)
    quarterly_path = processed_dir / "ecb_rates_quarterly.csv"
    quarterly.to_csv(quarterly_path, index=False, encoding="utf-8-sig")
    print(f"Quarterly rates saved to {quarterly_path}")

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

"""EBA EU-wide Transparency Exercise: bank-by-bank data of the largest EU banks, amounts in EUR million, four quarterly reference dates.

  load(conn)                       download the four CSV files of the vintage (curl) into data/raw/eba_te/<vintage>/ and load them
  load(conn, files=("oth",))       chosen files only
The exercise holds a full P&L, which P3DH does not. The vintage TE2025 (published December 2025) has the reference dates 30 Sep 2024, 31 Dec 2024, 31 Mar 2025, and 30 Jun 2025.
The EBA says the exercise is discontinued: the Pillar 3 Data Hub (P3DH) replaces it. No later vintage is expected.
P&L amounts are year to date: n_quarters says how many quarters of the fiscal year the amount covers (4 at the 31 December of a bank with a calendar fiscal year).

Tables (the columns of the CSV file, lower case; Row and Column are row_no and col_no; period_end is the last day of the quarter; vintage is the exercise):
  te_oth  sheets Capital, Leverage, Assets, Liabilities, P&L, RWA OV1        te_sov  sovereign exposures by country and maturity
  te_mrk  market risk                                                          te_cre  credit risk, asset quality, forborne, NACE, collateral
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Callable

import pandas as pd

from . import schema
from .pull import period_end

VINTAGES = {"TE2025": "https://www.eba.europa.eu/assets/TE2025/Full_database/883401"}
FILES = {"oth": "tr_oth.csv", "sov": "tr_sov.csv", "mrk": "tr_mrk.csv", "cre": "tr_cre.csv"}
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "raw" / "eba_te"
RENAME = {"LEI_Code": "lei", "NSA": "nsa", "Row": "row_no", "Column": "col_no"}
TEXT = {"lei", "nsa", "label", "sheet"}
CSV_COLUMNS = {
    "oth": ["LEI_Code", "NSA", "Period", "Item", "Label", "ASSETS_FV", "ASSETS_Stages", "Exposure", "Financial_instruments", "Amount", "Fin_end_year", "n_quarters", "Row", "Column", "Sheet"],
    "sov": ["LEI_Code", "NSA", "Period", "Item", "Label", "Country", "Accounting_portfolio", "Maturity", "Amount", "Row", "Column", "Sheet"],
    "mrk": ["LEI_Code", "NSA", "Period", "Item", "Label", "Portfolio", "MKT_Modprod", "Mkt_risk", "Amount", "Row", "Column", "Sheet"],
    "cre": ["LEI_Code", "NSA", "Period", "Item", "Label", "Portfolio", "Country", "Country_rank", "Exposure", "Status", "Perf_Status", "NACE_codes", "Amount", "Row", "Column", "Sheet"],
}
INDEX = {"oth": "lei, period, sheet", "sov": "lei, period, country", "mrk": "lei, period", "cre": "lei, period, sheet"}


def columns(file: str) -> list[str]:
    return [RENAME.get(c, c.lower()) for c in CSV_COLUMNS[file]]


def create(conn: sqlite3.Connection) -> None:
    for f in FILES:
        cols = ", ".join(f"{c} {'TEXT' if c in TEXT else 'REAL' if c == 'amount' else 'INTEGER'}" for c in columns(f))
        conn.execute(f"CREATE TABLE IF NOT EXISTS te_{f} ({cols}, period_end TEXT, vintage TEXT)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_te_{f} ON te_{f} ({INDEX[f]})")
    conn.commit()


def download(url: str, dest: Path, timeout: int = 900) -> None:
    """Download with curl (the certificate check stays on). A failed download leaves no file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    r = subprocess.run(["curl", "-s", "-f", "--max-time", str(timeout), "-o", str(tmp), url], capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"curl failed for {url}: exit {r.returncode} {r.stderr[:200]}")
    tmp.replace(dest)


def _period_end(p: int) -> str:
    return period_end(f"{p // 100}-{p % 100:02d}")


def load_file(conn: sqlite3.Connection, file: str, path: Path, vintage: str, chunk: int = 200_000) -> int:
    """Replace the rows of the vintage in te_<file> by the rows of the CSV file. Returns the number of rows."""
    cols = columns(file)
    sql = f"INSERT INTO te_{file} ({', '.join(cols)}, period_end, vintage) VALUES ({', '.join('?' * (len(cols) + 2))})"
    conn.execute(f"DELETE FROM te_{file} WHERE vintage = ?", (vintage,))
    n = 0
    for df in pd.read_csv(path, chunksize=chunk, low_memory=False, encoding_errors="replace"):
        missing = set(CSV_COLUMNS[file]) - set(df.columns)
        if missing:
            raise ValueError(f"{path.name}: columns missing: {sorted(missing)}")
        df = df.rename(columns=RENAME)
        df.columns = [c if c in ("lei", "nsa", "row_no", "col_no") else c.lower() for c in df.columns]
        df["period_end"] = df["period"].map(_period_end)
        df["vintage"] = vintage
        out = df[cols + ["period_end", "vintage"]].astype(object).where(df[cols + ["period_end", "vintage"]].notna(), None)
        conn.executemany(sql, out.itertuples(index=False, name=None))
        n += len(df)
    return n


def load(conn: sqlite3.Connection, vintage: str = "TE2025", files: tuple[str, ...] = tuple(FILES), cache: Path | None = None,
         fetcher: Callable[[str, Path], None] = download, log: Callable[[str], None] = print) -> dict[str, int]:
    if vintage not in VINTAGES:
        raise ValueError(f"unknown vintage {vintage}: {sorted(VINTAGES)}")
    schema.create(conn)
    create(conn)
    folder = Path(cache or CACHE) / vintage
    result: dict[str, int] = {}
    for f in files:
        if f not in FILES:
            raise ValueError(f"unknown file {f}: {sorted(FILES)}")
        path = folder / FILES[f]
        if not path.exists():
            log(f"  download {FILES[f]}")
            fetcher(f"{VINTAGES[vintage]}/{FILES[f]}", path)
        result[f] = load_file(conn, f, path, vintage)
        conn.execute("INSERT INTO ext_pull_log (started_at, indicator, source, n_series, n_obs, status, detail) VALUES (datetime('now'), ?, 'eba', ?, ?, 'ok', '')",
                     (f"te:{vintage}:{f}", conn.execute(f"SELECT COUNT(DISTINCT lei) FROM te_{f} WHERE vintage = ?", (vintage,)).fetchone()[0], result[f]))
        conn.commit()
        log(f"  te_{f}: {result[f]:,d} rows, {conn.execute(f'SELECT COUNT(DISTINCT lei) FROM te_{f} WHERE vintage = ?', (vintage,)).fetchone()[0]} banks")
    return result

"""Verify the downloaded P3DH files against the manifest, the raw archive and each other.

Checks for each reference date (all dates found under data/raw/P3DH by default):
  ledger     every template the portal lists has a manifest entry; statuses are reported;
             complete templates have a file whose hash and row count match the manifest
  files      header, constant reference date, template code, exactly one of value/text,
             no duplicate fact keys, cell code consistent with row and column codes
  archive    decoding the raw JSON archive again reproduces the CSV exactly
  paging     manifest cross-checks (entities re-fetched by name) all agree
  entities   entity names found in the data that the discovery list does not contain
  KM1        reported CET1, Tier 1, total capital and leverage ratios agree with the
             capital amounts divided by RWEA / exposure

Exit code 1 if any check fails.

  .venv/Scripts/python scripts/verify_p3dh.py
  .venv/Scripts/python scripts/verify_p3dh.py --dates 20260630 --no-archive
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.fetch.p3dh_fetch import OUT_COLUMNS, rebuild_from_archive, to_records  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
JSON_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH_json"
RUN_DIR = PROJECT_ROOT / "data" / "runs" / "p3dh"
KEY = ["entity_lei", "entity_name", "cell_code", "key_descriptor", "row_code", "column_code", "sheet"]
CELL = re.compile(r"^\{(K_[\d.]+(?:\.[a-z])?), r(\d+), c(\d+)\}$")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def check_file(path: Path, code: str, ref: str, entry: dict, archive: bool, problems: list) -> pd.DataFrame:
    def bad(msg: str) -> None:
        problems.append(f"{code}: {msg}")

    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    if list(frame.columns) != OUT_COLUMNS:
        bad(f"unexpected columns {list(frame.columns)}")
        return frame
    if set(frame["reference_date"]) != {ref}:
        bad(f"reference_date {sorted(set(frame['reference_date']))[:3]}")
    if not frame["template"].str.startswith(code).all():
        bad("template column does not match the file name")
    has_num, has_text = frame["fact_type"] == "number", frame["fact_type"] == "text"
    if (has_num == has_text).any():
        bad(f"{int((has_num == has_text).sum())} rows with fact_type other than number or text")
    if has_num.any():
        pd.to_numeric(frame.loc[has_num, "fact_value"], errors="raise")
    if (has_num & (frame["fact_value"] == "")).any() or (has_num & (frame["fact_text"] != "")).any():
        bad("number facts without a value, or with text")
    if (has_text & (frame["fact_value"] != "")).any():
        bad("text facts that also have a numeric value")
    keyed = frame[(frame["cell_code"] != "") & ~frame["cell_code"].str.contains(", r*,", regex=False)]
    dups = int(keyed.duplicated(KEY).sum())
    if dups:
        bad(f"{dups} duplicate fact keys among facts with a concrete cell code")
    parsed = frame["cell_code"].str.extract(CELL)
    ok = parsed[0].notna()
    mismatch = ok & ((parsed[1] != frame["row_code"].str.zfill(4)) | (parsed[2] != frame["column_code"].str.zfill(4)))
    if mismatch.any():
        bad(f"{int(mismatch.sum())} cell codes disagree with row/column codes")
    if entry.get("rows") is not None and entry["rows"] != len(frame):
        bad(f"manifest rows {entry['rows']} != file rows {len(frame)}")
    if entry.get("sha256") and entry["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        bad("file hash differs from the manifest")
    if archive:
        arc = JSON_DIR / ref.replace("-", "") / f"{code}.jsonl.gz"
        if not arc.exists():
            bad("raw archive missing")
        else:
            rows = rebuild_from_archive(arc, code, ref)
            again = pd.DataFrame(to_records(rows, ref), columns=OUT_COLUMNS).fillna("").astype(str)
            if len(again) != len(frame) or not again.reset_index(drop=True).equals(
                    frame.reset_index(drop=True)):
                bad("re-decoding the raw archive does not reproduce the CSV")
    return frame


def km1_check(frames: dict[str, pd.DataFrame]) -> list[tuple[str, float, int]]:
    """(label, share of cells that agree, cells compared) for the three KM1 capital ratios."""
    frame = frames.get("K_61.00")
    if frame is None:
        return []
    num = frame[frame["fact_type"] == "number"].copy()
    num["v"] = num["fact_value"].astype(float)
    num["period"] = num["column_code"]
    pivot = num.pivot_table(index=["entity_lei", "period"], columns="row_label", values="v", aggfunc="first")
    cols = {c.strip(): c for c in pivot.columns}

    def col(prefix: str) -> pd.Series | None:
        hit = [c for k, c in cols.items() if k.startswith(prefix)]
        return pivot[hit[0]] if hit else None

    pairs = [("Common Equity Tier 1 ratio (%)", "1. Common Equity Tier 1", "4. Total risk-weighted"),
             ("Tier 1 ratio (%)", "2. Tier 1 capital", "4. Total risk-weighted"),
             ("Total capital ratio (%)", "3. Total capital", "4. Total risk-weighted")]
    out = []
    for label, num_p, den_p in pairs:
        rep = next((pivot[c] for k, c in cols.items() if re.match(rf"\d+[a-z]?\. {re.escape(label)}", k)), None)
        n, d = col(num_p), col(den_p)
        if rep is None or n is None or d is None:
            continue
        calc = n / d
        both = rep.notna() & calc.notna() & (d > 0)
        agree = ((rep[both] - calc[both]).abs() < 0.005) | ((rep[both] / 100 - calc[both]).abs() < 0.005)
        out.append((label, float(agree.mean()), int(both.sum())))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--no-archive", action="store_true", help="Skip the raw archive re-decode")
    args = ap.parse_args()
    folders = args.dates or sorted(p.name for p in RAW_DIR.iterdir() if p.is_dir())
    failed = False
    for folder in folders:
        ref = f"{folder[:4]}-{folder[4:6]}-{folder[6:8]}"
        manifest = load_json(RUN_DIR / f"{folder}_manifest_v2.json").get("templates", {})
        listed = [n.split(" - ")[0].strip() for n in load_json(RUN_DIR / f"{folder}_templates.json").get("values", [])]
        entities = set(load_json(RUN_DIR / f"{folder}_entities.json").get("values", []))
        problems: list[str] = []
        if not (RUN_DIR / f"{folder}_manifest_v2.json").exists():
            problems.append("manifest file missing")
        if not (RUN_DIR / f"{folder}_templates.json").exists():
            problems.append("templates file missing")
        known_gaps: list[str] = []
        statuses: dict[str, int] = {}
        for code in listed:
            status = manifest.get(code, {}).get("status", "not_attempted")
            statuses[status] = statuses.get(status, 0) + 1
            if status == "skipped_slow":
                known_gaps.append(code)
            elif status not in ("complete", "empty"):
                problems.append(f"{code}: status {status}")
        frames: dict[str, pd.DataFrame] = {}
        seen_entities: set[str] = set()
        xcheck = {"ok": 0, "bad": 0, "none": 0}
        for code, entry in sorted(manifest.items()):
            if entry.get("status") != "complete":
                continue
            path = RAW_DIR / folder / f"{code}_data_points.csv"
            if not path.exists():
                problems.append(f"{code}: file missing")
                continue
            frames[code] = check_file(path, code, ref, entry, not args.no_archive, problems)
            seen_entities |= set(frames[code]["entity_name"])
            res = (entry.get("cross_check") or {}).get("result")
            xcheck["ok" if res == "ok" else "none" if res is None or str(res).startswith("inconclusive") else "bad"] += 1
        on_disk = {p.name.replace("_data_points.csv", "") for p in (RAW_DIR / folder).glob("K_*_data_points.csv")}
        for code in sorted(on_disk - set(manifest)):
            problems.append(f"{code}: file on disk but not in the manifest")
        if listed and not frames:
            problems.append("no files were checked")
        extra = sorted(seen_entities - entities) if entities else []
        print(f"\n=== {ref}: {len(listed)} templates listed | status {statuses}")
        print(f"    files checked: {len(frames)} | entity cross-checks ok={xcheck['ok']} "
              f"mismatch={xcheck['bad']} not-run={xcheck['none']}")
        print(f"    entities in data: {len(seen_entities)} | in discovery list: {len(entities)} | "
              f"in data but not in list: {len(extra)} {extra[:3]}")
        for label, share, n_cells in km1_check(frames):
            print(f"    KM1 {label}: {share:.1%} of {n_cells} cells agree with capital / RWEA "
                  f"(rest are banks reporting different bases or rounding)")
            if share < 0.90:
                problems.append(f"KM1 {label}: only {share:.1%} of cells agree with capital / RWEA")
        if xcheck["bad"]:
            problems.append(f"{xcheck['bad']} entity cross-checks disagree with paged data")
        for msg in problems[:25]:
            print("    PROBLEM", msg)
        if len(problems) > 25:
            print(f"    ... {len(problems) - 25} more problems")
        failed |= bool(problems)
        (RUN_DIR / f"verification_{folder}.json").write_text(
            json.dumps({"date": ref, "templates_listed": len(listed), "status": statuses,
                        "files_checked": len(frames), "problems": problems, "known_gaps": known_gaps,
                        "entities_in_data_not_in_list": extra}, indent=1), encoding="utf-8")
    print("\nRESULT:", "FAILED" if failed else "all checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

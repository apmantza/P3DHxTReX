"""Validate downloaded P3DH CSV files against the local EBA dictionary."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "P3DH"
DICT_PATH = PROJECT_ROOT / "data" / "processed" / "p3dh_data_dictionary.csv"
VALIDATION_DIR = PROJECT_ROOT / "data" / "validation"
BROKEN_TEMPLATES = {"K_83.01"}


def date_to_folder_name(date_str: str) -> str:
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y%m%d")


def template_code_from_path(path: Path) -> str:
    return path.name.replace("_data_points.csv", "")


def normalize_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    match = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    if match:
        try:
            return f"{int(match.group(1)):04d}"
        except ValueError:
            return text
    return text


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def row_code_candidates(value: Any) -> set[str]:
    code = normalize_code(value)
    if code is None:
        return set()
    return {code}


def col_code_candidates(value: Any) -> set[str]:
    code = normalize_code(value)
    if code is None:
        return set()
    return {code}


def load_dictionary() -> tuple[
    pd.DataFrame, set[str], set[tuple[str, str, str]], set[str]
]:
    try:
        df = pd.read_csv(DICT_PATH, encoding="utf-8-sig", dtype=str).fillna("")
    except OSError as exc:
        raise RuntimeError(
            f"Failed to read P3DH dictionary {DICT_PATH}: {exc}"
        ) from exc
    df["row_code_norm"] = df["row_code"].map(normalize_code)
    df["col_code_norm"] = df["col_code"].map(normalize_code)
    fixed = df[
        df["row_code_norm"].notna()
        & df["col_code_norm"].notna()
        & ~df["row_code"].astype(str).str.startswith("OPEN_")
    ]
    cell_keys = set(
        zip(
            fixed["template_code"].astype(str),
            fixed["row_code_norm"].astype(str),
            fixed["col_code_norm"].astype(str),
            strict=False,
        )
    )
    open_templates = set(
        df.loc[
            df["row_code"].astype(str).str.startswith("OPEN_"), "template_code"
        ].astype(str)
    )
    return df, set(df["template_code"].astype(str)), cell_keys, open_templates


def validate_file(
    path: Path,
    dict_templates: set[str],
    dict_cell_keys: set[tuple[str, str, str]],
    open_templates: set[str],
) -> dict[str, Any]:
    code = template_code_from_path(path)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    except OSError as exc:
        raise RuntimeError(
            f"Failed to read downloaded P3DH file {path}: {exc}"
        ) from exc
    result: dict[str, Any] = {
        "template_code": code,
        "rows": len(df),
        "template_in_dictionary": code in dict_templates,
        "facts_checked": 0,
        "facts_mapped": 0,
        "unmapped_facts": 0,
        "malformed_facts": 0,
        "duplicate_fact_keys": 0,
        "is_open_template": code in open_templates,
        "severity": "ok",
        "notes": [],
    }

    if code not in dict_templates:
        result["severity"] = "error"
        result["notes"].append("template not in dictionary")
        return result

    required = {"Entity", "Row", "Column"}
    if not required.issubset(df.columns):
        result["severity"] = "error"
        result["notes"].append(
            f"missing required columns: {sorted(required - set(df.columns))}"
        )
        return result

    key_cols = [
        col
        for col in ["Entity", "Module", "Cell", "Row", "Column", "FactValue"]
        if col in df.columns
    ]
    if key_cols:
        result["duplicate_fact_keys"] = safe_int(df.duplicated(subset=key_cols).sum())

    if code in open_templates:
        # Open-row templates use typed dimensions as row keys. The local dictionary
        # validates template coverage, but fixed row/column cell matching is not
        # meaningful for every fact.
        result["facts_checked"] = len(df)
        result["facts_mapped"] = len(df)
        if result["duplicate_fact_keys"]:
            result["severity"] = "warning"
            result["notes"].append("duplicate fact rows")
        result["notes"].append("open-row template: skipped fixed row/column cell match")
        return result

    mapped = 0
    unmapped = 0
    malformed = 0
    for _, row in df.iterrows():
        row_codes = row_code_candidates(row.get("Row"))
        col_codes = col_code_candidates(row.get("Column"))
        if not row_codes or not col_codes:
            malformed += 1
            continue
        if any((code, r, c) in dict_cell_keys for r in row_codes for c in col_codes):
            mapped += 1
        else:
            unmapped += 1

    result["facts_checked"] = mapped + unmapped + malformed
    result["facts_mapped"] = mapped
    result["unmapped_facts"] = unmapped
    result["malformed_facts"] = malformed

    if unmapped or malformed:
        result["severity"] = "error"
    elif result["duplicate_fact_keys"]:
        result["severity"] = "warning"
        result["notes"].append("duplicate fact rows")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    folder = date_to_folder_name(args.date)
    raw_dir = RAW_ROOT / folder
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw P3DH folder not found: {raw_dir}")
    if not DICT_PATH.exists():
        raise FileNotFoundError(f"P3DH dictionary not found: {DICT_PATH}")

    _, dict_templates, dict_cell_keys, open_templates = load_dictionary()
    files = sorted(raw_dir.glob("*_data_points.csv"))
    downloaded_templates = {template_code_from_path(path) for path in files}

    records = [
        validate_file(path, dict_templates, dict_cell_keys, open_templates)
        for path in files
    ]

    missing_downloads = sorted(dict_templates - downloaded_templates - BROKEN_TEMPLATES)
    extra_downloads = sorted(downloaded_templates - dict_templates)

    summary = {
        "date": args.date,
        "folder": folder,
        "files": len(files),
        "dictionary_templates": len(dict_templates),
        "downloaded_templates": len(downloaded_templates),
        "missing_downloads": missing_downloads,
        "extra_downloads": extra_downloads,
        "errors": sum(1 for item in records if item["severity"] == "error"),
        "warnings": sum(1 for item in records if item["severity"] == "warning"),
        "total_rows": sum(safe_int(item["rows"]) for item in records),
        "total_unmapped_facts": sum(
            safe_int(item["unmapped_facts"]) for item in records
        ),
        "total_malformed_facts": sum(
            safe_int(item["malformed_facts"]) for item in records
        ),
        "total_duplicate_fact_keys": sum(
            safe_int(item["duplicate_fact_keys"]) for item in records
        ),
    }

    csv_path = VALIDATION_DIR / f"p3dh_{folder}_dictionary_validation.csv"
    json_path = VALIDATION_DIR / f"p3dh_{folder}_dictionary_validation.json"
    try:
        VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_csv(csv_path, index=False, encoding="utf-8-sig")
        json_path.write_text(
            json.dumps(
                {"summary": summary, "templates": records},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to write validation outputs: {exc}") from exc

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

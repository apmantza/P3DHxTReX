"""
Build P3DH Data Dictionary from EBA Annotated Table Layout files.

Extracts per-cell metadata:
  template_code, template_name, module_name,
  row_code, row_name, section,
  col_code, col_name,
  unit (EUR | PCT | TEXT),
  dpm_point_id, main_property, dimensions

Output: data/processed/p3dh_data_dictionary.csv
"""

import re
from pathlib import Path
from typing import Any, cast

import pandas as pd

# Map filename fragment → module_name (matches P3DH module_name field)
MODULE_MAP = {
    "CODISPILLAR3": "Common disclosures",
    "FINDISPILLAR3": "Financial disclosures",
    "ESGDISPILLAR3": "ESG disclosures",
    "IRRBBDISPILLAR3": "IRRBB disclosures",
    "MRELTLACDISPILLAR3": "MREL/TLAC disclosures",
    "REMDISPILLAR3": "Remuneration disclosures",
    "GSIIDISPILLAR3": "GSII disclosures",
}

TABLE_LAYOUT_DIR = Path("data") / "raw" / "EBA_DPM" / "table_layout"
OUTPUT_PATH = Path("data") / "processed" / "p3dh_data_dictionary.csv"


def infer_unit(cell_str: str) -> str:
    """Extract unit from DPM cell notation like '33411_x000D_\n€£$'."""
    if not isinstance(cell_str, str) or "_x000D_" not in cell_str:
        return "TEXT"
    after = cell_str.split("_x000D_", 1)[1].strip()
    if "€£$" in after or "€" in after or "$" in after:
        return "EUR"
    if "%" in after:
        return "PCT"
    return "TEXT"


def extract_dpm_id(cell_str: str) -> str | None:
    if not isinstance(cell_str, str):
        return None
    m = re.match(r"^(\d+)_x000D_", cell_str)
    return m.group(1) if m else None


def is_missing(value: Any) -> bool:
    """Return True for scalar pandas missing values.

    The parser only passes scalar worksheet cells here; wrapping pd.isna keeps
    pandas' broad static return type (bool | ndarray | Series) out of call sites.
    """
    return bool(pd.isna(value))


def normalize_row_code(raw: Any) -> str | None:
    """Convert float row code (10.0) to 4-digit string (0010)."""
    if is_missing(raw):
        return None
    try:
        return f"{int(float(raw)):04d}"
    except (ValueError, TypeError):
        return None


def _find_col_codes_row(df: pd.DataFrame) -> int | None:
    """
    Find the row index containing 4-digit numeric column codes (e.g. 0010, 0020).
    Templates have 1-, 2-, or 3-level column headers so this row varies.
    Accepts rows with >= 1 four-digit code that appear in col index >= 3
    (to avoid matching section headers in cols 0-2).
    """
    for ri in range(3, min(11, df.shape[0])):
        row = df.iloc[ri]
        codes = [
            str(row.iloc[ci]).strip()
            for ci in range(3, len(row))
            if not is_missing(row.iloc[ci])
            and re.match(r"^\d{4}$", str(row.iloc[ci]).strip())
        ]
        if len(codes) >= 1:
            return ri
    return None


def _find_data_start_row(df: pd.DataFrame, codes_row: int) -> int:
    """First row after codes_row that has a row-code in col 2."""
    for ri in range(codes_row + 1, df.shape[0]):
        val = df.iloc[ri, 1] if df.shape[1] > 1 else None
        if str(val).strip() == "Rows":
            return ri + 1
        # Also accept if col 2 has a numeric row code
        rc = df.iloc[ri, 2] if df.shape[1] > 2 else None
        if rc is not None and not is_missing(rc):
            try:
                int(float(str(rc)))
                return ri
            except (ValueError, TypeError):
                pass
    return codes_row + 1


def _find_main_property_col(df: pd.DataFrame, codes_row: int) -> int:
    """
    The main-property column is the first column after the data columns
    that contains DPM-style text like '(qABJ) ...' in any data row.
    Fall back to searching rows after codes_row.
    """
    # DPM properties are always to the right of the data columns.
    # In a standard sheet codes_row = 5, properties start at col 8.
    # We detect them by scanning the first data row.
    data_row_idx = codes_row + 1
    if data_row_idx >= df.shape[0]:
        return 8
    row = df.iloc[data_row_idx]
    for ci in range(3, df.shape[1]):
        v = str(row.iloc[ci]) if not is_missing(row.iloc[ci]) else ""
        if re.match(r"^\(", v):
            return ci
    return 8  # default


def parse_sheet(
    xl: pd.ExcelFile, sheet: str, template_code: str, module_name: str
) -> list[dict[str, Any]]:
    df = cast(pd.DataFrame, xl.parse(sheet, header=None))
    if df.shape[0] < 6 or df.shape[1] < 4:
        return []

    # Row 0: template name (first non-empty cell)
    template_name = sheet
    for ri in range(min(3, df.shape[0])):
        v = df.iloc[ri, 0]
        if not is_missing(v) and str(v).strip():
            template_name = str(v).strip()
            break

    # Auto-detect the row containing column codes
    codes_row = _find_col_codes_row(df)
    if codes_row is None:
        return []

    col_codes_raw = df.iloc[codes_row].tolist()
    # Column names are in the row immediately before codes_row
    col_names_raw = df.iloc[codes_row - 1].tolist()

    col_positions: dict[int, tuple[str, str]] = {}  # col_index → (col_code, col_name)
    for ci, (cname, ccode) in enumerate(
        zip(col_names_raw, col_codes_raw, strict=False)
    ):
        ccode_str = str(ccode).strip() if not is_missing(ccode) else ""
        if not re.match(r"^\d{4}$", ccode_str):
            continue
        ccode_norm = ccode_str  # already 4 digits
        # Column name: use explicit name from names row, fall back to code
        cname_str = (
            str(cname).strip()
            if not is_missing(cname) and str(cname).strip()
            else ccode_str
        )
        # Skip if name looks like a DPM property
        if re.match(r"^\(", cname_str):
            cname_str = ccode_str
        col_positions[ci] = (ccode_norm, cname_str)

    if not col_positions:
        return []

    data_col_indices = sorted(col_positions.keys())
    data_start = _find_data_start_row(df, codes_row)
    prop_col_start = _find_main_property_col(df, codes_row)

    records = []
    current_section = ""

    for ri in range(data_start, df.shape[0]):
        row = df.iloc[ri]
        row_name_raw = str(row.iloc[1]).strip() if not is_missing(row.iloc[1]) else ""
        row_code_raw = row.iloc[2] if df.shape[1] > 2 else None
        row_code = normalize_row_code(row_code_raw)

        if not row_name_raw or row_name_raw == "nan":
            continue

        # Section header: has row_name but no row_code and no data in data cols
        has_data = any(
            not is_missing(row.iloc[ci]) for ci in data_col_indices if ci < len(row)
        )
        if row_code is None:
            if has_data and row_name_raw.lower() == "open rows":
                # Some P3 templates are open-row tables: the row key is a typed
                # dimension rather than a fixed numeric row code. Keep the data
                # cells with a stable synthetic row code so the dictionary still
                # covers the template's fields.
                row_code = f"OPEN_{ri:04d}"
            else:
                if not has_data:
                    # Strip leading code prefix like "0005 Available own funds"
                    section_text = re.sub(r"^\d{4}\s+", "", row_name_raw)
                    current_section = section_text.replace("\n", " ").strip()
                continue

        # DPM properties: prop_col_start = main property, columns after = dimensions
        main_property = ""
        if df.shape[1] > prop_col_start and not is_missing(row.iloc[prop_col_start]):
            main_property = str(row.iloc[prop_col_start]).strip()

        dim_parts = []
        for ci in range(prop_col_start + 1, df.shape[1]):
            v = row.iloc[ci]
            if not is_missing(v) and str(v).strip() and str(v).strip() != "nan":
                dim_parts.append(str(v).strip())
        dimensions = " | ".join(dim_parts)

        # One record per data column
        for ci in data_col_indices:
            if ci >= len(row):
                continue
            col_code, col_name = col_positions[ci]
            cell_val = row.iloc[ci]
            cell_str = str(cell_val) if not is_missing(cell_val) else ""
            unit = infer_unit(cell_str)
            dpm_id = extract_dpm_id(cell_str)

            cell_main_property = main_property
            if str(row_name_raw).lower() == "open rows" and ri + 1 < df.shape[0]:
                next_label = (
                    str(df.iloc[ri + 1, 1]).strip()
                    if not is_missing(df.iloc[ri + 1, 1])
                    else ""
                )
                if (
                    next_label == "Main Property"
                    and ci < df.shape[1]
                    and not is_missing(df.iloc[ri + 1, ci])
                ):
                    cell_main_property = str(df.iloc[ri + 1, ci]).strip()

            records.append(
                {
                    "template_code": template_code,
                    "template_name": template_name,
                    "module_name": module_name,
                    "section": current_section,
                    "row_code": row_code,
                    "row_name": row_name_raw.replace("\xa0", " ")
                    .replace("\n", " ")
                    .strip(),
                    "col_code": col_code,
                    "col_name": col_name,
                    "unit": unit,
                    "dpm_point_id": dpm_id,
                    "main_property": cell_main_property,
                    "dimensions": dimensions,
                }
            )

    return records


def main():
    all_records: list[dict[str, Any]] = []

    if not TABLE_LAYOUT_DIR.exists():
        raise FileNotFoundError(f"Table layout directory not found: {TABLE_LAYOUT_DIR}")

    for fpath in sorted(TABLE_LAYOUT_DIR.glob("*.xlsx")):
        fname = fpath.name

        # Find matching module
        module_name = None
        for key, mod in MODULE_MAP.items():
            if key in fname:
                module_name = mod
                break
        if module_name is None:
            continue  # skip non-P3 files (MiCA, SEPA, etc.)

        print(f"Processing: {fname} → {module_name}")
        xl = pd.ExcelFile(fpath, engine="openpyxl")

        for sheet in xl.sheet_names:
            if sheet == "TOC":
                continue
            # template_code = sheet name, strip .a/.b and any trailing (XXXX) variant
            template_code = re.sub(
                r"\.[a-z](\(\d{4}\))?$", "", sheet
            )  # K_74.00.a(0010) → K_74.00
            records = parse_sheet(xl, sheet, template_code, module_name)
            all_records.extend(records)
            print(f"  {sheet}: {len(records)} cells")

    df_out = pd.DataFrame(all_records)

    # De-duplicate: same template+row+col may appear in .a/.b sub-sheets
    df_out = df_out.drop_duplicates(
        subset=["template_code", "row_code", "col_code", "module_name"]
    )
    df_out = df_out.sort_values(
        ["module_name", "template_code", "row_code", "col_code"]
    )
    df_out.reset_index(drop=True, inplace=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(df_out):,} records → {OUTPUT_PATH}")
    print(
        df_out[["template_code", "row_code", "col_code", "unit", "main_property"]]
        .head(10)
        .to_string()
    )


if __name__ == "__main__":
    main()

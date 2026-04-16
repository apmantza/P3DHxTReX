from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pandas as pd

from modules.ingestion.common import as_path, require_paths


P3DH_EXPORT_SHEET = "Export"


def extract_reference_date(filename: str) -> str | None:
    """Extract reference date from P3DH filename like 20250630_common_disclosures.xlsx."""
    match = re.match(r"(\d{8})_", filename)
    if not match:
        return None
    date_str = match.group(1)
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def extract_reference_date_from_path(path: str | Path) -> str | None:
    """Extract reference date from filename or parent folders like 20251231."""
    file_path = as_path(path)

    from_name = extract_reference_date(file_path.name)
    if from_name:
        return from_name

    for part in reversed(file_path.parts):
        match = re.fullmatch(r"(\d{8})", part)
        if match:
            date_str = match.group(1)
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return None


def _extract_template_from_cell(cell_value: str | float | int | None) -> str | None:
    if cell_value is None or pd.isna(cell_value):
        return None
    match = re.search(r"\{\s*(K_[0-9]{2}\.[0-9]{2})\s*,", str(cell_value))
    return match.group(1) if match else None


def _extract_row_from_cell(cell_value: str | float | int | None) -> str | None:
    if cell_value is None or pd.isna(cell_value):
        return None
    match = re.search(r",\s*r(\d{4})\s*,", str(cell_value))
    return match.group(1) if match else None


def _extract_column_from_cell(cell_value: str | float | int | None) -> str | None:
    if cell_value is None or pd.isna(cell_value):
        return None
    match = re.search(r",\s*c(\d{4})\s*\}", str(cell_value))
    return match.group(1) if match else None


def _normalize_code(value: object) -> str | pd.NA:
    if value is None or pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text:
        return pd.NA
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if re.fullmatch(r"\d+", text):
        return text.zfill(4)
    return text


def normalize_p3dh_export(excel_path: str | Path) -> pd.DataFrame:
    """Normalize P3DH Export sheet into long format."""
    path = as_path(excel_path)
    require_paths([path])

    raw = pd.read_excel(path, sheet_name=P3DH_EXPORT_SHEET, header=None)
    if raw.shape[0] < 3:
        raise ValueError("P3DH export sheet is empty or missing header rows")

    header_dates = raw.iloc[0]
    header_fields = raw.iloc[1]

    data = raw.iloc[2:].copy()
    columns = []
    for idx in range(len(raw.columns)):
        if idx <= 10:
            columns.append(str(header_fields.iloc[idx]).strip())
        else:
            columns.append(header_dates.iloc[idx])

    data.columns = columns

    id_cols = columns[:11]
    date_cols = columns[11:]

    normalized = data.melt(
        id_vars=id_cols,
        value_vars=date_cols,
        var_name="ReferenceDate",
        value_name="FactValue",
    )

    normalized = normalized.rename(
        columns={
            "Entity Name": "entity_name",
            "Country": "country",
            "Module Name": "module_name",
            "Cell": "cell",
            "Open Key": "open_key",
            "Template": "template",
            "Row": "row",
            "Row Name": "row_name",
            "Column": "column",
            "Column Name": "column_name",
            "Sheet": "sheet",
            "ReferenceDate": "reference_date",
            "FactValue": "fact_value",
        }
    )

    normalized = normalized[normalized["fact_value"].notna()].copy()
    normalized["reference_date"] = pd.to_datetime(
        normalized["reference_date"], errors="coerce"
    )
    normalized["fact_value"] = pd.to_numeric(normalized["fact_value"], errors="coerce")

    ref_date = extract_reference_date_from_path(excel_path)
    if ref_date:
        normalized["file_reference_date"] = ref_date

    return normalized


def _extract_template_from_filename(filename: str) -> str | None:
    """Extract template code like 'K_68.00' from filename like 'K_68.00_data_points.csv'."""
    match = re.match(r"(K_\d{2}\.\d{2})_data_points", filename)
    return match.group(1) if match else None


def _is_lei_format(frame: pd.DataFrame) -> bool:
    """Detect whether the CSV uses the LEI format where Entity column contains LEI codes.

    Since late 2024, EBA P3DH API CSVs shifted to a format where:
      Entity = LEI code (20-char alphanumeric), not bank name
      Country = Bank name (not the country)
      Module = Actual country (not the module name)
      Cell = Module name like 'IRRBB disclosures' (not {K_xx, rYY, cZZ})
    """
    if "Entity" not in frame.columns:
        return False
    entity_col = frame["Entity"].dropna().astype(str).str.strip()
    if entity_col.empty:
        return False
    # Check first 10 non-empty entities: if most look like LEIs (20-char alphanumeric), it's LEI format
    sample = entity_col.head(10)
    lei_match = sample.str.fullmatch(r"[A-Z0-9]{20}")
    return lei_match.sum() >= len(sample) * 0.5


def normalize_p3dh_api_csv(csv_path: str | Path) -> pd.DataFrame:
    """Normalize API-downloaded P3DH CSV files into the common long schema.

    Handles two formats:
    1. Legacy format: Entity=BankName, Country=Country, Module=ModuleName, Cell={K_xx, rYY, cZZ}
    2. LEI format (since late 2024): Entity=LEI, Country=BankName, Module=Country, Cell=ModuleName
    """
    path = as_path(csv_path)
    require_paths([path])

    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    if frame.empty:
        return pd.DataFrame()

    lei_format = _is_lei_format(frame)

    if lei_format:
        return _normalize_p3dh_api_csv_lei_format(frame, path)
    else:
        return _normalize_p3dh_api_csv_legacy_format(frame, path)


def _normalize_p3dh_api_csv_legacy_format(
    frame: pd.DataFrame, path: Path
) -> pd.DataFrame:
    """Normalize legacy-format P3DH CSV where Entity=BankName, Country=Country."""
    normalized = frame.rename(
        columns={
            "Entity": "entity_name",
            "Country": "country",
            "Module": "module_name",
            "Cell": "cell",
            "Row": "row",
            "RowName": "row_name",
            "Column": "column",
            "ColumnName": "column_name",
            "FactValue": "fact_value",
        }
    ).copy()

    for col in [
        "entity_name",
        "country",
        "module_name",
        "cell",
        "row",
        "row_name",
        "column",
        "column_name",
    ]:
        if col in normalized.columns:
            normalized[col] = normalized[col].astype("string")

    normalized["template"] = normalized.get(
        "cell", pd.Series(index=normalized.index)
    ).map(_extract_template_from_cell)
    normalized["row"] = normalized["row"].where(
        normalized["row"].notna() & (normalized["row"].astype(str).str.strip() != ""),
        normalized["cell"].map(_extract_row_from_cell),
    )
    normalized["column"] = normalized["column"].where(
        normalized["column"].notna()
        & (normalized["column"].astype(str).str.strip() != ""),
        normalized["cell"].map(_extract_column_from_cell),
    )

    normalized["template"] = normalized["template"].astype("string")

    normalized["entity_name"] = normalized["entity_name"].ffill()
    normalized["country"] = (
        normalized.groupby("entity_name", dropna=False)["country"].ffill().bfill()
    )
    normalized["module_name"] = (
        normalized.groupby("entity_name", dropna=False)["module_name"].ffill().bfill()
    )
    normalized["template"] = (
        normalized.groupby("entity_name", dropna=False)["template"].ffill().bfill()
    )
    normalized["row_name"] = (
        normalized.groupby(["entity_name", "template", "row"], dropna=False)["row_name"]
        .ffill()
        .bfill()
    )
    normalized["column_name"] = (
        normalized.groupby(["entity_name", "template", "column"], dropna=False)[
            "column_name"
        ]
        .ffill()
        .bfill()
    )

    normalized["row"] = normalized["row"].map(_normalize_code)
    normalized["column"] = normalized["column"].map(_normalize_code)
    normalized["entity_name"] = normalized["entity_name"].astype(object)
    normalized["country"] = normalized["country"].astype(object)
    normalized["module_name"] = normalized["module_name"].astype(object)
    normalized["cell"] = normalized["cell"].astype(object)
    normalized["template"] = normalized["template"].astype(object)
    normalized["row_name"] = normalized["row_name"].astype(object)
    normalized["column_name"] = normalized["column_name"].astype(object)

    normalized["open_key"] = pd.NA
    normalized["sheet"] = pd.NA

    ref_date = extract_reference_date_from_path(path)
    normalized["reference_date"] = pd.to_datetime(ref_date, errors="coerce")
    normalized["fact_value"] = pd.to_numeric(normalized["fact_value"], errors="coerce")

    normalized = normalized[
        [
            "entity_name",
            "country",
            "module_name",
            "cell",
            "open_key",
            "template",
            "row",
            "row_name",
            "column",
            "column_name",
            "sheet",
            "reference_date",
            "fact_value",
        ]
    ].copy()

    normalized = normalized[normalized["fact_value"].notna()].copy()
    return normalized


def _normalize_p3dh_api_csv_lei_format(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Normalize LEI-format P3DH CSV where Entity=LEI, Country=BankName, Module=Country, Cell=ModuleName.

    The EBA P3DH API shifted to a new CSV format where:
      Entity  = 20-char LEI code (not bank name)
      Country = Bank name (not the country)
      Module  = Actual country (not module name)
      Cell    = Module name like 'IRRBB disclosures' (not {K_xx, rYY, cZZ})
      Row     = 0-based row index (not row code like r0010)
      RowName = Usually empty; row labels appear in ColumnName

    This function remaps columns to the standard schema and derives the template
    code from the filename (e.g., K_68.00_data_points.csv -> K_68.00).
    """
    # Derive template code from filename (e.g., K_68.00_data_points.csv -> K_68.00)
    template_code = _extract_template_from_filename(path.name)

    # Remap LEI-format columns to our canonical schema
    normalized = frame.rename(
        columns={
            "Entity": "lei",  # LEI code (keep as separate field)
            "Country": "entity_name",  # Bank name is in the Country column
            "Module": "country",  # Actual country is in the Module column
            "Cell": "module_name",  # Module name (like 'IRRBB disclosures')
            "Row": "row_index",  # 0-based index (not usable as row code)
            "RowName": "row_name",
            "Column": "column",
            "ColumnName": "column_name",
            "FactValue": "fact_value",
        }
    ).copy()

    # Drop original columns we renamed from, if they still exist
    for drop_col in ["entity_name_orig", "country_orig"]:
        if drop_col in normalized.columns:
            normalized.drop(columns=[drop_col], inplace=True)

    for col in [
        "lei",
        "entity_name",
        "country",
        "module_name",
        "row_name",
        "column",
        "column_name",
    ]:
        if col in normalized.columns:
            normalized[col] = normalized[col].astype("string")

    # Fill entity_name and country per LEI group since CSV has these per-entity header rows
    normalized["entity_name"] = normalized["entity_name"].ffill()
    normalized["country"] = (
        normalized.groupby("lei", dropna=False)["country"].ffill().bfill()
    )
    normalized["module_name"] = (
        normalized.groupby("lei", dropna=False)["module_name"].ffill().bfill()
    )

    # Template: use filename-derived code for all rows in this file
    normalized["template"] = template_code

    # Column codes: these come as 4-digit strings in the CSV ('0010', '0020', etc.)
    # Some rows have empty columns (label rows)
    normalized["column"] = normalized["column"].map(_normalize_code)

    # Row codes: in LEI format, Row is a 0-based index, not a code.
    # We keep it as-is for now (normalized) but it's not the canonical row code.
    # The actual row code should be derived from row_name patterns or the data dictionary.
    # For now, convert the index to a zero-padded string.
    normalized["row_index"] = normalized["row_index"].map(_normalize_code)
    # Use row_index as row code placeholder (will be enhanced when matching data dict)
    normalized["row"] = normalized["row_index"]

    # Forward-fill row_name and column_name within entity groups
    normalized["row_name"] = normalized.groupby(["lei", "template"], dropna=False)[
        "row_name"
    ].ffill()
    normalized["column_name"] = normalized.groupby(["lei", "template"], dropna=False)[
        "column_name"
    ].ffill()

    # Some row_name values contain the template code (e.g., 'K_30.04 - EU REM4 - ...')
    # These are label rows; set their template from the row_name if different from filename
    # (This handles mixed-modules common-disclosure CSVs)
    normalized["row_name_template"] = normalized["row_name"].map(
        _extract_row_name_template
    )

    # Type conversions
    normalized["entity_name"] = normalized["entity_name"].astype(object)
    normalized["country"] = normalized["country"].astype(object)
    normalized["module_name"] = normalized["module_name"].astype(object)
    normalized["template"] = normalized["template"].astype(object)
    normalized["row"] = normalized["row"].astype(object)
    normalized["row_name"] = normalized["row_name"].astype(object)
    normalized["column"] = normalized["column"].astype(object)
    normalized["column_name"] = normalized["column_name"].astype(object)

    # Build cell value: in LEI format we don't have {K_xx, rYY, cZZ}
    # Use a synthetic cell from template + row + column
    normalized["cell"] = normalized.apply(
        lambda r: (
            f"{{{r['template']}, r{r['row']}, c{r['column']}}}"
            if pd.notna(r["template"]) and pd.notna(r["row"]) and pd.notna(r["column"])
            else None
        ),
        axis=1,
    )
    normalized["cell"] = normalized["cell"].astype(object)

    normalized["open_key"] = pd.NA
    normalized["sheet"] = pd.NA

    ref_date = extract_reference_date_from_path(path)
    normalized["reference_date"] = pd.to_datetime(ref_date, errors="coerce")
    normalized["fact_value"] = pd.to_numeric(normalized["fact_value"], errors="coerce")

    # Select final columns (drop lei and helper columns)
    normalized = normalized[
        [
            "entity_name",
            "country",
            "module_name",
            "cell",
            "open_key",
            "template",
            "row",
            "row_name",
            "column",
            "column_name",
            "sheet",
            "reference_date",
            "fact_value",
        ]
    ].copy()

    normalized = normalized[normalized["fact_value"].notna()].copy()
    return normalized


def _extract_row_name_template(row_name: str) -> str | None:
    """Extract template code from row_name like 'K_30.04 - EU REM4 - ...'."""
    if row_name is None or pd.isna(row_name):
        return None
    match = re.match(r"(K_\d{2}\.\d{2})\s*-", str(row_name).strip())
    return match.group(1) if match else None


def scan_p3dh_directory(p3dh_dir: str | Path) -> Iterator[tuple[Path, pd.DataFrame]]:
    """Scan directory for legacy Excel and API CSV P3DH exports."""
    dir_path = as_path(p3dh_dir)

    for xlsx_file in sorted(dir_path.rglob("*.xlsx")):
        try:
            df = normalize_p3dh_export(xlsx_file)
            yield xlsx_file.name, df
        except Exception as e:
            print(f"Skipping {xlsx_file.name}: {e}")

    for csv_file in sorted(dir_path.rglob("*.csv")):
        try:
            df = normalize_p3dh_api_csv(csv_file)
            yield csv_file.relative_to(dir_path), df
        except Exception as e:
            print(f"Skipping {csv_file.name}: {e}")
    """Scan directory for legacy Excel and API CSV P3DH exports."""
    dir_path = as_path(p3dh_dir)

    for xlsx_file in sorted(dir_path.rglob("*.xlsx")):
        try:
            df = normalize_p3dh_export(xlsx_file)
            yield xlsx_file.name, df
        except Exception as e:
            print(f"Skipping {xlsx_file.name}: {e}")

    for csv_file in sorted(dir_path.rglob("*.csv")):
        try:
            df = normalize_p3dh_api_csv(csv_file)
            yield csv_file.relative_to(dir_path), df
        except Exception as e:
            print(f"Skipping {csv_file.name}: {e}")


def normalize_all_p3dh(p3dh_dir: str | Path) -> pd.DataFrame:
    """Normalize all P3DH Excel files in directory into one DataFrame."""
    frames = []
    for filename, df in scan_p3dh_directory(p3dh_dir):
        frames.append(df)
        print(f"Loaded {filename}: {len(df.index)} rows")
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined


def build_p3dh_key(frame: pd.DataFrame) -> pd.Series:
    """Create a stable key for incremental ingestion."""
    key_cols = [
        "entity_name",
        "template",
        "row",
        "column",
        "cell",
        "reference_date",
    ]
    missing = [col for col in key_cols if col not in frame.columns]
    if missing:
        raise ValueError(f"Missing key columns for P3DH: {', '.join(missing)}")
    return frame[key_cols].astype(str).agg("|".join, axis=1)


def with_key_column(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with a stable key column for upserts."""
    keyed = frame.copy()
    keyed["p3dh_key"] = build_p3dh_key(keyed)
    return keyed


def split_incremental(
    new_frame: pd.DataFrame,
    existing_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split new data into append and skipped sets."""
    path = as_path(existing_path)
    if path.exists():
        existing = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        existing_keys = build_p3dh_key(existing)
        new_keys = build_p3dh_key(new_frame)
        mask_new = ~new_keys.isin(set(existing_keys))
        to_append = new_frame[mask_new].copy()
        skipped = new_frame[~mask_new].copy()
        return to_append, skipped, existing

    return new_frame.copy(), pd.DataFrame(), pd.DataFrame()


def append_incremental(
    new_frame: pd.DataFrame,
    existing_path: str | Path,
) -> tuple[pd.DataFrame, int, int]:
    """Append only new rows vs existing CSV snapshot."""
    to_append, skipped, existing = split_incremental(new_frame, existing_path)
    if not existing.empty:
        combined = pd.concat([existing, to_append], ignore_index=True)
    else:
        combined = to_append.copy()
    return combined, len(to_append.index), len(skipped.index)


def export_skipped_keys(
    new_frame: pd.DataFrame,
    existing_path: str | Path,
    output_path: str | Path,
) -> int:
    """Export skipped keys (already ingested) to CSV."""
    path = as_path(existing_path)
    if not path.exists():
        return 0
    existing = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    existing_keys = build_p3dh_key(existing)
    new_keys = build_p3dh_key(new_frame)
    mask_skipped = new_keys.isin(set(existing_keys))
    skipped = new_frame[mask_skipped].copy()
    if skipped.empty:
        return 0
    skipped = with_key_column(skipped)
    out = as_path(output_path)
    skipped[["p3dh_key"]].drop_duplicates().to_csv(
        out, index=False, encoding="utf-8-sig"
    )
    return len(skipped.index)


def upsert_p3dh_sqlite(
    frame: pd.DataFrame,
    sqlite_path: str | Path,
    table_name: str = "p3dh_facts",
) -> tuple[int, int]:
    """Insert normalized P3DH rows into SQLite with upsert semantics."""
    import sqlite3

    path = as_path(sqlite_path)
    keyed = with_key_column(frame)
    keyed = keyed.copy()
    keyed["reference_date"] = keyed["reference_date"].dt.strftime("%Y-%m-%d")
    keyed = keyed.where(pd.notna(keyed), None)

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                p3dh_key TEXT PRIMARY KEY,
                entity_name TEXT,
                country TEXT,
                module_name TEXT,
                cell TEXT,
                open_key TEXT,
                template TEXT,
                row TEXT,
                row_name TEXT,
                column TEXT,
                column_name TEXT,
                sheet TEXT,
                reference_date TEXT,
                fact_value REAL
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_refdate ON {table_name}(reference_date)"
        )

        before = conn.total_changes
        records = keyed[
            [
                "p3dh_key",
                "entity_name",
                "country",
                "module_name",
                "cell",
                "open_key",
                "template",
                "row",
                "row_name",
                "column",
                "column_name",
                "sheet",
                "reference_date",
                "fact_value",
            ]
        ].itertuples(index=False, name=None)

        conn.executemany(
            f"""
            INSERT OR IGNORE INTO {table_name} (
                p3dh_key, entity_name, country, module_name, cell, open_key,
                template, row, row_name, column, column_name, sheet,
                reference_date, fact_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
        after = conn.total_changes
        inserted = after - before
        skipped = len(keyed.index) - inserted
        return int(inserted), int(skipped)
    finally:
        conn.close()

"""Build a normalized SQLite database from downloaded P3DH CSV files.

The raw Power BI export columns are intentionally preserved in bronze CSVs. This
loader creates a silver, long-form schema suitable for cross-template queries and
future time series.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "P3DH"
RUN_DIR = PROJECT_ROOT / "data" / "runs" / "p3dh"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DICT_PATH = PROCESSED_DIR / "p3dh_data_dictionary.csv"
TEMPLATE_SUMMARY_PATH = (
    PROJECT_ROOT / "data" / "reference" / "p3dh" / "p3dh_template_summary.csv"
)
DEFAULT_DB = PROCESSED_DIR / "p3dh.sqlite"


def date_to_folder_name(date_str: str) -> str:
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y%m%d")


def iso_date_from_folder(folder: str) -> str:
    return f"{folder[:4]}-{folder[4:6]}-{folder[6:8]}"


def template_code_from_path(path: Path) -> str:
    return path.name.replace("_data_points.csv", "")


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    match = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    if match:
        return f"{safe_int(match.group(1)):04d}"
    return text


def clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def numeric_value(value: Any) -> float | None:
    text = clean_text(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def is_open_key(value: Any) -> bool:
    text = clean_text(value)
    return bool(text and (" = " in text or " | " in text))


def parse_open_key(open_key: str | None) -> list[tuple[str, str]]:
    if not open_key:
        return []
    parts = [part.strip() for part in open_key.split("|")]
    dimensions: list[tuple[str, str]] = []
    for part in parts:
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            dimensions.append((name, value))
    return dimensions


def make_fact_id(parts: list[Any]) -> str:
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    except OSError as exc:
        raise RuntimeError(f"Failed to read raw CSV {path}: {exc}") from exc


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"templates": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load manifest {path}: {exc}") from exc


def connect(db_path: Path, replace: bool) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if replace and db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dim_run (
            run_id TEXT PRIMARY KEY,
            reference_date TEXT NOT NULL,
            folder TEXT NOT NULL,
            manifest_path TEXT,
            loaded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS extraction_manifest (
            reference_date TEXT NOT NULL,
            template_code TEXT NOT NULL,
            status TEXT NOT NULL,
            rows INTEGER,
            template_restart_token INTEGER,
            entity_restart_token_count INTEGER,
            row_partition_restart_token_count INTEGER,
            failed_entities_json TEXT,
            reason TEXT,
            updated_at TEXT,
            PRIMARY KEY (reference_date, template_code)
        );

        CREATE TABLE IF NOT EXISTS dim_institution (
            lei TEXT PRIMARY KEY,
            entity_name TEXT,
            country TEXT
        );

        CREATE TABLE IF NOT EXISTS dim_template (
            template_code TEXT PRIMARY KEY,
            template_name TEXT,
            module_name TEXT,
            cells INTEGER,
            rows INTEGER,
            columns INTEGER,
            dpm_points INTEGER,
            is_open_row INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS dim_cell (
            template_code TEXT NOT NULL,
            row_code TEXT NOT NULL,
            col_code TEXT NOT NULL,
            row_name TEXT,
            col_name TEXT,
            module_name TEXT,
            unit TEXT,
            dpm_point_id TEXT,
            main_property TEXT,
            dimensions TEXT,
            PRIMARY KEY (template_code, row_code, col_code)
        );

        CREATE TABLE IF NOT EXISTS p3dh_fact (
            fact_id TEXT PRIMARY KEY,
            reference_date TEXT NOT NULL,
            template_code TEXT NOT NULL,
            lei TEXT,
            entity_name TEXT,
            country TEXT,
            module_name TEXT,
            cell TEXT,
            row_code TEXT,
            row_label TEXT,
            row_raw TEXT,
            open_key TEXT,
            column_code TEXT,
            column_label TEXT,
            fact_value_raw TEXT,
            fact_value_num REAL,
            source_file TEXT,
            run_id TEXT
        );

        CREATE TABLE IF NOT EXISTS p3dh_fact_dimension (
            fact_id TEXT NOT NULL,
            dimension_name TEXT NOT NULL,
            dimension_value TEXT,
            PRIMARY KEY (fact_id, dimension_name, dimension_value),
            FOREIGN KEY (fact_id) REFERENCES p3dh_fact(fact_id) ON DELETE CASCADE
        );
        """
    )


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_fact_date_template ON p3dh_fact(reference_date, template_code);
        CREATE INDEX IF NOT EXISTS idx_fact_lei ON p3dh_fact(lei);
        CREATE INDEX IF NOT EXISTS idx_fact_template_row_col ON p3dh_fact(template_code, row_code, column_code);
        CREATE INDEX IF NOT EXISTS idx_fact_dim_name_value ON p3dh_fact_dimension(dimension_name, dimension_value);
        """
    )


def load_dictionary(conn: sqlite3.Connection) -> None:
    if TEMPLATE_SUMMARY_PATH.exists():
        summary = pd.read_csv(
            TEMPLATE_SUMMARY_PATH, encoding="utf-8-sig", dtype=str
        ).fillna("")
        for _, row in summary.iterrows():
            conn.execute(
                """
                INSERT INTO dim_template(template_code, template_name, module_name, cells, rows, columns, dpm_points)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_code) DO UPDATE SET
                  template_name=excluded.template_name,
                  module_name=excluded.module_name,
                  cells=excluded.cells,
                  rows=excluded.rows,
                  columns=excluded.columns,
                  dpm_points=excluded.dpm_points
                """,
                (
                    clean_text(row.get("template_code")),
                    clean_text(row.get("template_name")),
                    clean_text(row.get("module_name")),
                    safe_int(row.get("cells")),
                    safe_int(row.get("rows")),
                    safe_int(row.get("columns")),
                    safe_int(row.get("dpm_points")),
                ),
            )
    if not DICT_PATH.exists():
        return
    dictionary = pd.read_csv(DICT_PATH, encoding="utf-8-sig", dtype=str).fillna("")
    open_templates: set[str] = set()
    for _, row in dictionary.iterrows():
        template = clean_text(row.get("template_code"))
        row_code = normalize_code(row.get("row_code"))
        col_code = normalize_code(row.get("col_code"))
        if not template or not row_code or not col_code:
            continue
        if row_code.startswith("OPEN_"):
            open_templates.add(template)
        conn.execute(
            """
            INSERT OR REPLACE INTO dim_cell(
              template_code, row_code, col_code, row_name, col_name, module_name,
              unit, dpm_point_id, main_property, dimensions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template,
                row_code,
                col_code,
                clean_text(row.get("row_name")),
                clean_text(row.get("col_name")),
                clean_text(row.get("module_name")),
                clean_text(row.get("unit")),
                clean_text(row.get("dpm_point_id")),
                clean_text(row.get("main_property")),
                clean_text(row.get("dimensions")),
            ),
        )
    for template in open_templates:
        conn.execute(
            "INSERT INTO dim_template(template_code, is_open_row) VALUES (?, 1) "
            "ON CONFLICT(template_code) DO UPDATE SET is_open_row=1",
            (template,),
        )


def load_manifest_table(
    conn: sqlite3.Connection, reference_date: str, manifest: dict[str, Any]
) -> None:
    for code, item in manifest.get("templates", {}).items():
        failed = item.get("failed_entities", [])
        conn.execute(
            """
            INSERT OR REPLACE INTO extraction_manifest(
              reference_date, template_code, status, rows, template_restart_token,
              entity_restart_token_count, row_partition_restart_token_count,
              failed_entities_json, reason, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_date,
                code,
                item.get("status"),
                safe_int(item.get("rows")),
                1 if item.get("template_restart_token") else 0,
                safe_int(item.get("entity_restart_token_count")),
                safe_int(item.get("row_partition_restart_token_count")),
                json.dumps(failed, ensure_ascii=False),
                item.get("reason"),
                item.get("updated_at"),
            ),
        )


def normalize_raw_frame(
    path: Path, reference_date: str, run_id: str
) -> tuple[
    list[tuple[Any, ...]],
    list[tuple[str, str | None, str | None]],
    list[tuple[str, str, str]],
]:
    template_code = template_code_from_path(path)
    frame = read_csv(path)
    facts: list[tuple[Any, ...]] = []
    institutions: dict[str, tuple[str | None, str | None]] = {}
    dimensions: list[tuple[str, str, str]] = []

    for _, row in frame.iterrows():
        lei = clean_text(row.get("Entity"))
        entity_name = clean_text(row.get("Country"))
        country = clean_text(row.get("Module"))
        module_name = clean_text(row.get("Cell"))
        row_raw = clean_text(row.get("Row"))
        row_label = clean_text(row.get("RowName"))
        column_code = normalize_code(row.get("Column"))
        column_label = clean_text(row.get("ColumnName"))
        fact_raw = clean_text(row.get("FactValue"))
        if fact_raw is None:
            continue

        open_key = row_raw if is_open_key(row_raw) else None
        row_code = None if open_key else normalize_code(row_raw)
        fact_num = numeric_value(fact_raw)
        cell = (
            f"{{{template_code}, r{row_code}, c{column_code}}}"
            if row_code and column_code
            else None
        )
        fact_id = make_fact_id(
            [
                reference_date,
                template_code,
                lei,
                module_name,
                cell,
                row_code,
                row_label,
                row_raw,
                open_key,
                column_code,
                column_label,
                fact_raw,
            ]
        )
        facts.append(
            (
                fact_id,
                reference_date,
                template_code,
                lei,
                entity_name,
                country,
                module_name,
                cell,
                row_code,
                row_label,
                row_raw,
                open_key,
                column_code,
                column_label,
                fact_raw,
                fact_num,
                path.name,
                run_id,
            )
        )
        if lei:
            institutions[lei] = (entity_name, country)
        for dim_name, dim_value in parse_open_key(open_key):
            dimensions.append((fact_id, dim_name, dim_value))

    institution_rows = [
        (lei, values[0], values[1]) for lei, values in institutions.items()
    ]
    return facts, institution_rows, dimensions


def load_facts(
    conn: sqlite3.Connection, raw_dir: Path, reference_date: str, run_id: str
) -> int:
    files = sorted(raw_dir.glob("*_data_points.csv"))
    total = 0
    for path in files:
        facts, institutions, dimensions = normalize_raw_frame(
            path, reference_date, run_id
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO dim_institution(lei, entity_name, country)
            VALUES (?, ?, ?)
            """,
            institutions,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO p3dh_fact(
              fact_id, reference_date, template_code, lei, entity_name, country,
              module_name, cell, row_code, row_label, row_raw, open_key,
              column_code, column_label, fact_value_raw, fact_value_num,
              source_file, run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            facts,
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO p3dh_fact_dimension(fact_id, dimension_name, dimension_value)
            VALUES (?, ?, ?)
            """,
            dimensions,
        )
        total += len(facts)
        print(f"Loaded {path.name}: {len(facts):,} facts")
    return total


def create_template_views(conn: sqlite3.Connection) -> None:
    codes = [
        row[0]
        for row in conn.execute(
            "SELECT template_code FROM dim_template ORDER BY template_code"
        )
    ]
    for code in codes:
        view_name = "v_p3dh_" + code.replace(".", "_").replace("-", "_")
        conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')
        conn.execute(
            f'CREATE VIEW "{view_name}" AS SELECT * FROM p3dh_fact WHERE template_code = {code!r}'
        )


def build_database(date_str: str, db_path: Path, replace: bool) -> dict[str, Any]:
    folder = date_to_folder_name(date_str)
    reference_date = iso_date_from_folder(folder)
    raw_dir = RAW_ROOT / folder
    manifest_path = RUN_DIR / f"{folder}_manifest.json"
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw P3DH folder not found: {raw_dir}")
    manifest = load_manifest(manifest_path)
    run_id = f"p3dh_{folder}"

    conn = connect(db_path, replace=replace)
    try:
        create_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO dim_run(run_id, reference_date, folder, manifest_path, loaded_at) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                reference_date,
                folder,
                str(manifest_path),
                datetime.now().isoformat(),
            ),
        )
        load_dictionary(conn)
        load_manifest_table(conn, reference_date, manifest)
        total_facts = load_facts(conn, raw_dir, reference_date, run_id)
        create_indexes(conn)
        create_template_views(conn)
        conn.commit()
        summary = {
            "db_path": str(db_path),
            "reference_date": reference_date,
            "facts": total_facts,
            "institutions": conn.execute(
                "SELECT COUNT(*) FROM dim_institution"
            ).fetchone()[0],
            "templates_in_manifest": conn.execute(
                "SELECT COUNT(*) FROM extraction_manifest"
            ).fetchone()[0],
            "completed_templates": conn.execute(
                "SELECT COUNT(*) FROM extraction_manifest WHERE status='complete'"
            ).fetchone()[0],
            "skipped_templates": conn.execute(
                "SELECT COUNT(*) FROM extraction_manifest WHERE status='skipped'"
            ).fetchone()[0],
            "open_dimensions": conn.execute(
                "SELECT COUNT(*) FROM p3dh_fact_dimension"
            ).fetchone()[0],
        }
        return summary
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--replace", action="store_true", help="Replace existing SQLite database"
    )
    args = parser.parse_args()

    summary = build_database(args.date, args.db, args.replace)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Build or update the P3DH SQLite database from the downloaded raw files.

Reads data/raw/P3DH/<yyyymmdd>/K_xx.xx_data_points.csv (output of scripts/download_p3dh.py)
and loads them incrementally: a (reference date, template) is reloaded only when the file
hash changed. Nothing is deleted except the facts of the file being reloaded.

Tables
  filing         one row per (reference_date, template_code): status, hash, counts
  dim_template   every template the portal lists for a date, with the full title
  entity         LEI, name, country
  fact           one row per fact; primary key (date, template, entity, seq). seq is the
                 position in the file, so facts without a cell code (open-table labels)
                 cannot collide. Facts with a cell code are unique by (cell, key, sheet).
Views
  v_fact         fact joined with entity
  v_coverage     every listed template with its download status and fact count
  v_period_fact  facts of columns labelled 'T' or 'T-n' with period_end (T = the reference
                 date, T-n = n periods earlier). Only templates listed in period_template are
                 included, because 'T-n' does not mean n quarters in every template (for
                 example OR1 uses years and LR2 uses disclosure periods). KM1 and OV1 are
                 quarterly. The period comes from the label, not the code:
                 OV1 column 'c. T' is the own funds requirement at T. measure_col is the
                 column code minus 10 * period offset: the same measure has the same
                 measure_col in every filing (KM1 'b. T-1' in one filing is 'a. T' in the next).
  v_latest_period_fact  one row per entity, table, quarter, row and measure: the value from
                        the latest filing

Usage
  .venv/Scripts/python scripts/build_p3dh_db.py
  .venv/Scripts/python scripts/build_p3dh_db.py --dates 20251231 --db other.sqlite
  .venv/Scripts/python scripts/build_p3dh_db.py --rebuild     # delete the DB file and reload
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "P3DH"
RUN_DIR = PROJECT_ROOT / "data" / "runs" / "p3dh"
DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"

FACT_COLUMNS = [
    "reference_date", "template_code", "entity_id", "seq", "cell_code", "key_descriptor", "sheet",
    "module_code", "module_name", "row_code", "row_label", "column_code", "column_label",
    "value", "value_text",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS filing (
    reference_date TEXT NOT NULL,
    template_code TEXT NOT NULL,
    status TEXT,
    source_file TEXT,
    sha256 TEXT,
    n_facts INTEGER,
    n_entities INTEGER,
    n_entities_empty INTEGER,
    n_entities_failed INTEGER,
    n_entities_truncated INTEGER,
    requests INTEGER,
    downloaded_at TEXT,
    loaded_at TEXT,
    PRIMARY KEY (reference_date, template_code)
);
CREATE TABLE IF NOT EXISTS dim_template (
    reference_date TEXT NOT NULL,
    template_code TEXT NOT NULL,
    title TEXT,
    PRIMARY KEY (reference_date, template_code)
);
CREATE TABLE IF NOT EXISTS entity (
    entity_id INTEGER PRIMARY KEY,
    lei TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    country TEXT,
    last_seen TEXT,
    entity_key TEXT,
    UNIQUE (lei, entity_name)
);
CREATE TABLE IF NOT EXISTS period_template (
    template_code TEXT PRIMARY KEY,
    months_per_period INTEGER NOT NULL,
    max_offset INTEGER NOT NULL DEFAULT 4
);
CREATE TABLE IF NOT EXISTS fact (
    reference_date TEXT NOT NULL,
    template_code TEXT NOT NULL,
    entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
    seq INTEGER NOT NULL,
    cell_code TEXT NOT NULL DEFAULT '',
    key_descriptor TEXT NOT NULL DEFAULT '',
    sheet TEXT NOT NULL DEFAULT '',
    module_code TEXT,
    module_name TEXT,
    row_code TEXT,
    row_label TEXT,
    column_code TEXT,
    column_label TEXT,
    value REAL,
    value_text TEXT,
    PRIMARY KEY (reference_date, template_code, entity_id, seq),
    CHECK ((value IS NULL) <> (value_text IS NULL))
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_fact_entity ON fact(entity_id, template_code, reference_date);
CREATE INDEX IF NOT EXISTS idx_fact_cell ON fact(template_code, row_code, column_code);
CREATE INDEX IF NOT EXISTS idx_fact_key ON fact(reference_date, template_code, entity_id, cell_code, key_descriptor, sheet);
"""

VIEWS = """
DROP VIEW IF EXISTS v_fact;
CREATE VIEW v_fact AS
SELECT f.*, e.lei, e.entity_name, e.country, e.entity_key
FROM fact f JOIN entity e ON e.entity_id = f.entity_id;

DROP VIEW IF EXISTS v_coverage;
CREATE VIEW v_coverage AS
SELECT d.reference_date, d.template_code, d.title,
       COALESCE(fi.status, 'not_downloaded') AS status,
       fi.n_facts, fi.n_entities, fi.n_entities_failed, fi.n_entities_truncated
FROM dim_template d
LEFT JOIN filing fi ON fi.reference_date = d.reference_date AND fi.template_code = d.template_code;

DROP VIEW IF EXISTS v_period_fact;
CREATE VIEW v_period_fact AS
SELECT q.*,
       date(q.reference_date, 'start of month', '-' || (q.months_per_period * q.period_offset) || ' months',
            '+1 month', '-1 day') AS period_end,
       CAST(q.column_code AS INTEGER) - 10 * q.period_offset AS measure_col
FROM (
    SELECT f.*, e.lei, e.entity_name, e.country, e.entity_key, pt.months_per_period, pt.max_offset,
           CASE WHEN f.cell_code LIKE '{%,%' THEN SUBSTR(f.cell_code, 2, INSTR(f.cell_code, ',') - 2)
                ELSE f.template_code END AS table_code,
           CASE WHEN INSTR(f.column_label, 'T-') > 0
                THEN CAST(SUBSTR(f.column_label, INSTR(f.column_label, 'T-') + 2) AS INTEGER)
                ELSE 0 END AS period_offset
    FROM fact f
    JOIN entity e ON e.entity_id = f.entity_id
    JOIN period_template pt ON pt.template_code = f.template_code
    WHERE (f.column_label GLOB '[a-z]. T' OR f.column_label GLOB '[a-z]. T-[0-9]*')
      AND SUBSTR(f.reference_date, 6, 2) IN ('03', '06', '09', '12')
) q
WHERE q.period_offset <= q.max_offset;

DROP VIEW IF EXISTS v_latest_period_fact;
CREATE VIEW v_latest_period_fact AS
SELECT * FROM (
    SELECT p.*, ROW_NUMBER() OVER (
        PARTITION BY p.entity_key, p.template_code, p.period_end, p.row_code, p.key_descriptor, p.sheet,
                     p.measure_col
        ORDER BY p.reference_date DESC, p.table_code ASC) AS rn
    FROM v_period_fact p
    WHERE p.value IS NOT NULL
) WHERE rn = 1;
"""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def iso(folder: str) -> str:
    return f"{folder[:4]}-{folder[4:6]}-{folder[6:8]}"


def load_templates(conn: sqlite3.Connection, folder: str) -> int:
    payload = load_json(RUN_DIR / f"{folder}_templates.json")
    if payload.get("source") != "live":
        return 0
    rows = []
    for name in payload.get("values", []):
        code, _, title = name.partition(" - ")
        rows.append((iso(folder), code.strip(), title.strip() or None))
    conn.executemany("INSERT OR REPLACE INTO dim_template VALUES (?, ?, ?)", rows)
    return len(rows)


def load_file(conn: sqlite3.Connection, path: Path, folder: str, manifest: dict) -> str:
    code = path.name.replace("_data_points.csv", "")
    ref = iso(folder)
    digest = sha256_of(path)
    old = conn.execute(
        "SELECT sha256 FROM filing WHERE reference_date = ? AND template_code = ?", (ref, code)
    ).fetchone()
    m = manifest.get("templates", {}).get(code, {})
    if old and old[0] == digest:
        conn.execute(
            """UPDATE filing SET status = ?, n_entities_empty = ?, n_entities_failed = ?,
                      n_entities_truncated = ?, requests = ?, downloaded_at = ?
               WHERE reference_date = ? AND template_code = ?""",
            (m.get("status", "unknown"), m.get("entities_empty"), m.get("entities_failed"),
             m.get("entities_truncated"), m.get("requests"), m.get("updated_at"), ref, code))
        return "unchanged"

    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    problems = []
    if set(frame["reference_date"]) != {ref}:
        problems.append(f"reference_date values {sorted(set(frame['reference_date']))[:3]}")
    if not frame["template"].str.startswith(code).all():
        problems.append("template column does not match file name")
    if problems:
        raise ValueError(f"{path.name}: {'; '.join(problems)}")

    frame = frame.rename(columns={"entity_lei": "lei", "fact_value": "value",
                                  "fact_text": "value_text", "template": "template_code"})
    frame["template_code"] = code
    has_num, has_text = frame["fact_type"] == "number", frame["fact_type"] == "text"
    if (has_num == has_text).any():
        raise ValueError(f"{path.name}: fact_type must be 'number' or 'text'")
    if (has_num & (frame["value"] == "")).any() or (has_num & (frame["value_text"] != "")).any():
        raise ValueError(f"{path.name}: a number fact has no value or has text")
    frame["value"] = pd.to_numeric(frame["value"].replace("", None), errors="raise")
    frame["value_text"] = frame["value_text"].where(has_text, None)
    ents_frame = frame.drop_duplicates(["lei", "entity_name"])[["lei", "entity_name", "country"]]

    with conn:
        conn.execute("DELETE FROM fact WHERE reference_date = ? AND template_code = ?", (ref, code))
        conn.executemany(
            """INSERT INTO entity (lei, entity_name, country, last_seen) VALUES (?, ?, ?, ?)
               ON CONFLICT(lei, entity_name) DO UPDATE SET
                 country = excluded.country,
                 last_seen = MAX(excluded.last_seen, entity.last_seen)""",
            [(r.lei, r.entity_name, r.country, ref) for r in ents_frame.itertuples(index=False)],
        )
        ids = {(lei, name): eid for eid, lei, name in
               conn.execute("SELECT entity_id, lei, entity_name FROM entity")}
        frame["entity_id"] = [ids[k] for k in zip(frame["lei"], frame["entity_name"])]
        frame["seq"] = frame.groupby("entity_id").cumcount()
        facts = frame[FACT_COLUMNS].astype(object).where(frame[FACT_COLUMNS].notna(), None)
        conn.executemany(
            f"INSERT INTO fact ({', '.join(FACT_COLUMNS)}) VALUES ({', '.join('?' * len(FACT_COLUMNS))})",
            facts.itertuples(index=False, name=None),
        )
        conn.execute(
            "INSERT OR REPLACE INTO filing VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ref, code, m.get("status", "unknown"), str(path.relative_to(PROJECT_ROOT)), digest,
             len(facts), int(frame["entity_id"].nunique()), m.get("entities_empty"),
             m.get("entities_failed"), m.get("entities_truncated"), m.get("requests"),
             m.get("updated_at"), datetime.now().isoformat(timespec="seconds")),
        )
    return "loaded" if not old else "reloaded"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dates", nargs="*", help="Folders such as 20251231 (default: all)")
    ap.add_argument("--rebuild", action="store_true", help="Delete the DB file first (it is derived data)")
    args = ap.parse_args()

    if args.rebuild and args.db.exists():
        args.db.unlink()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)

    folders = args.dates or sorted(p.name for p in RAW_ROOT.iterdir() if p.is_dir())
    counts = {"loaded": 0, "reloaded": 0, "unchanged": 0, "error": 0}
    for folder in folders:
        manifest = load_json(RUN_DIR / f"{folder}_manifest_v2.json")
        n_tpl = load_templates(conn, folder)
        files = sorted((RAW_ROOT / folder).glob("K_*_data_points.csv"))
        print(f"{folder}: {len(files)} files, {n_tpl} templates listed", flush=True)
        for path in files:
            try:
                counts[load_file(conn, path, folder, manifest)] += 1
            except Exception as exc:  # noqa: BLE001
                counts["error"] += 1
                print(f"  ERROR {path.name}: {exc}", file=sys.stderr)
        # manifest entries without a file (empty, failed_server, error)
        for code, m in manifest.get("templates", {}).items():
            if not (RAW_ROOT / folder / f"{code}_data_points.csv").exists():
                conn.execute(
                    "INSERT OR REPLACE INTO filing (reference_date, template_code, status, downloaded_at, loaded_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (iso(folder), code, m.get("status"), m.get("updated_at"),
                     datetime.now().isoformat(timespec="seconds")),
                )
        conn.commit()

    if "max_offset" not in {r[1] for r in conn.execute("PRAGMA table_info(period_template)")}:
        conn.execute("ALTER TABLE period_template ADD COLUMN max_offset INTEGER NOT NULL DEFAULT 4")
    # KM1 columns T to T-4 are quarters. In OV1, T-1 is the previous disclosure date: 3, 6 or
    # 12 months back, depending on the bank. Only the T column of OV1 enters the period views.
    conn.executemany("INSERT OR REPLACE INTO period_template VALUES (?, ?, ?)",
                     [("K_60.00", 3, 0), ("K_61.00", 3, 4)])
    # An LEI is one entity across filings (names change after renames and mergers). It is
    # two entities only if one filing holds the LEI under two names.
    conn.execute("UPDATE entity SET entity_key = lei")
    conn.execute(
        """UPDATE entity SET entity_key = lei || '|' || entity_name WHERE lei IN (
               SELECT lei FROM (SELECT DISTINCT e.lei AS lei, f.reference_date AS d, f.entity_id AS id
                                FROM fact f JOIN entity e ON e.entity_id = f.entity_id)
               GROUP BY lei, d HAVING COUNT(*) > 1)""")
    conn.executescript(VIEWS)
    conn.commit()
    # The latest view keeps one row per key. A tie is two rows of one filing that share the key
    # and the sort values (same filing, same sub-table). A tie makes the choice arbitrary.
    dup_groups = conn.execute(
        """SELECT COUNT(*) FROM (SELECT 1 FROM v_period_fact
           GROUP BY entity_key, template_code, period_end, row_code, key_descriptor, sheet, measure_col,
                    reference_date, table_code
           HAVING COUNT(*) > 1)""").fetchone()[0]

    # integrity: fact counts must equal the ledger
    bad = conn.execute(
        """SELECT fi.reference_date, fi.template_code, fi.n_facts, COUNT(f.entity_id)
           FROM filing fi LEFT JOIN fact f
             ON f.reference_date = fi.reference_date AND f.template_code = fi.template_code
           WHERE fi.sha256 IS NOT NULL
           GROUP BY fi.reference_date, fi.template_code
           HAVING COUNT(f.entity_id) <> fi.n_facts"""
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM fact").fetchone()[0]
    ents = conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
    print(f"loaded={counts['loaded']} reloaded={counts['reloaded']} unchanged={counts['unchanged']} "
          f"errors={counts['error']} | facts={total:,} entities={ents:,} | "
          f"ledger mismatches={len(bad)} | latest-view duplicate groups={dup_groups} | "
          f"integrity={conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    for row in bad:
        print("  MISMATCH", row, file=sys.stderr)
    conn.close()
    return 1 if counts["error"] or bad or dup_groups else 0


if __name__ == "__main__":
    raise SystemExit(main())

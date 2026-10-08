"""Rebuild the CSVs from the raw response archive with the current decoder (no network).

  .venv/Scripts/python scripts/redecode_p3dh.py                 # all dates
  .venv/Scripts/python scripts/redecode_p3dh.py --dates 20260331
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.fetch.p3dh_fetch import OUT_COLUMNS, rebuild_from_archive, to_records  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
RUN_DIR = PROJECT_ROOT / "data" / "runs" / "p3dh"
JSON_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH_json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*")
    args = ap.parse_args()
    folders = args.dates or sorted(p.name for p in JSON_DIR.iterdir() if p.is_dir())
    changed = errors = 0
    for folder in folders:
        date_iso = f"{folder[:4]}-{folder[4:6]}-{folder[6:8]}"
        manifest_path = RUN_DIR / f"{folder}_manifest_v2.json"
        updates: dict[str, dict] = {}
        for archive in sorted((JSON_DIR / folder).glob("K_*.jsonl.gz")):
            code = archive.name.replace(".jsonl.gz", "")
            try:
                rows = rebuild_from_archive(archive, code, date_iso)
                frame = pd.DataFrame(to_records(rows, date_iso), columns=OUT_COLUMNS)
                out = RAW_DIR / folder / f"{code}_data_points.csv"
                tmp = out.with_suffix(".csv.tmp")
                frame.to_csv(tmp, index=False, encoding="utf-8")
                before = hashlib.sha256(out.read_bytes()).hexdigest() if out.exists() else None
                tmp.replace(out)
                after = hashlib.sha256(out.read_bytes()).hexdigest()
                changed += before != after
                updates[code] = {"sha256": after, "rows": len(frame),
                                 "entities_with_rows": int(frame["entity_lei"].nunique())}
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"ERROR {folder}/{code}: {exc}", file=sys.stderr)
        if updates and manifest_path.exists():
            # read the manifest again now and change only the three fields, then replace the file
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for code, fields in updates.items():
                if code in manifest.get("templates", {}):
                    manifest["templates"][code].update(fields)
            tmp = manifest_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(manifest_path)
        print(f"{folder}: done", flush=True)
    print(f"files changed: {changed}, errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Concurrent P3DH download — discover once, then download all templates in parallel."""

from __future__ import annotations

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
CDP_URL = "http://localhost:9222"
REPORT_URL = "https://edap-public.eba.europa.eu/Report/index/MTE2"

# Known broken templates (EBA-side API errors)
BROKEN_TEMPLATES = {"K_83.01"}


def load_api_token(date_str: str) -> tuple[str, dict, dict]:
    """Capture a fresh API token via browser."""
    from scripts.download_via_api import (
        capture_token_and_query,
        ensure_chrome_debugging,
        get_templates,
    )

    ensure_chrome_debugging()

    with sync_playwright() as p:
        templates = get_templates(p, date_str)
        seed = templates[0] if templates else "K_00.02 - Accompanying narrative CODIS"
        captured = capture_token_and_query(p, date_str, seed)

    if not captured:
        raise RuntimeError("Failed to capture API token")

    return captured["url"], dict(captured["headers"]), json.loads(captured["post_data"])


def modify_query(base_query: dict, template: str, max_rows: int = 5000) -> dict:
    """Modify query to target a specific template."""
    query = json.loads(json.dumps(base_query))
    cmd = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]

    for where in cmd["Query"].get("Where", []):
        condition = where.get("Condition", {})
        if "In" in condition:
            expr = condition["In"]["Expressions"][0]
            if expr.get("Column", {}).get("Property") == "Template":
                condition["In"]["Values"] = [[{"Literal": {"Value": f"'{template}'"}}]]

    def raise_data_reduction_counts(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "Count" and isinstance(value, int):
                    obj[key] = max_rows
                else:
                    raise_data_reduction_counts(value)
        elif isinstance(obj, list):
            for item in obj:
                raise_data_reduction_counts(item)

    if "Binding" in cmd and "DataReduction" in cmd["Binding"]:
        raise_data_reduction_counts(cmd["Binding"]["DataReduction"])

    return query


def execute_query(url: str, headers: dict, query: dict, timeout: int = 300) -> dict:
    resp = requests.post(url, headers=headers, data=json.dumps(query), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse_response(data: dict) -> pd.DataFrame:
    """Parse PowerBI DSR response."""
    result = data["results"][0]["result"]["data"]
    dsr_data = result["dsr"]

    if "DS" not in dsr_data:
        log.warning("  No 'DS' in DSR, keys: %s", list(dsr_data.keys()))
        return pd.DataFrame()

    dsr = dsr_data["DS"][0]
    value_dicts = dsr.get("ValueDicts", {})
    g_to_d = {1: "D0", 2: "D1", 3: "D2", 5: "D5", 6: "D6", 7: "D7", 8: "D8"}

    def resolve(g_idx, val):
        if g_idx in g_to_d:
            d_key = g_to_d[g_idx]
            if d_key in value_dicts and isinstance(val, (int, float)):
                idx = int(val)
                if idx < len(value_dicts[d_key]):
                    return value_dicts[d_key][idx]
        return val

    rows = []

    def parse_level(obj, context, depth=0):
        if depth > 15:
            return
        ctx = dict(context)
        for key in obj:
            if key.startswith("G"):
                g_idx = int(key[1:])
                ctx[g_idx] = obj[key]
        if "X" in obj:
            for x in obj["X"]:
                if "M0" in x:
                    val_raw = x["M0"]
                    if isinstance(val_raw, str):
                        val_str = val_raw[:-1] if val_raw.endswith("D") else val_raw
                        try:
                            val = float(val_str)
                        except Exception:
                            val = val_raw
                    elif isinstance(val_raw, (int, float)):
                        val = float(val_raw)
                    else:
                        val = val_raw
                    rows.append(
                        {
                            "Entity": ctx.get(0, ""),
                            "Country": resolve(1, ctx.get(1, "")),
                            "Module": resolve(2, ctx.get(2, "")),
                            "Cell": resolve(3, ctx.get(3, "")),
                            "Row": resolve(5, ctx.get(5, "")),
                            "RowName": resolve(6, ctx.get(6, "")),
                            "Column": resolve(7, ctx.get(7, "")),
                            "ColumnName": resolve(8, ctx.get(8, "")),
                            "FactValue": val,
                        }
                    )
        if "M" in obj:
            for m in obj["M"]:
                for key in m:
                    if key.startswith("DM"):
                        for dm in m[key]:
                            parse_level(dm, ctx, depth + 1)

    ph = dsr["PH"][0]
    for dm0 in ph["DM0"]:
        entity = dm0.get("G0", "")
        context = {0: entity}
        if "M" in dm0:
            for m in dm0["M"]:
                for key in m:
                    if key.startswith("DM"):
                        for dm in m[key]:
                            parse_level(dm, context, 1)

    return pd.DataFrame(rows)


def download_single_template(
    url: str,
    headers: dict,
    base_query: dict,
    template: str,
    output_dir: Path,
) -> tuple[str, int]:
    """Download one template via API."""
    code = template.split(" - ")[0].strip()
    output_path = output_dir / f"{code}_data_points.csv"

    if code in BROKEN_TEMPLATES:
        return code, -1  # Skip known broken templates

    try:
        modified = modify_query(base_query, template)
        data = execute_query(url, headers, modified, timeout=300)
        for ds in (
            data.get("results", [])[0]
            .get("result", {})
            .get("data", {})
            .get("dsr", {})
            .get("DS", [])
        ):
            for msg in ds.get("Msg", []):
                log.warning("  %s Power BI message: %s", code, msg.get("Message", msg))
        df = parse_response(data)

        if df.empty:
            return code, 0

        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return code, len(df)

    except Exception as e:
        log.error("  %s failed: %s", code, e)
        return code, -2


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="31/12/2025")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    date_str = args.date
    folder_name = datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y%m%d")
    output_dir = Path(args.output_dir) / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Discover templates from portal (one browser session)
    log.info("Discovering templates from portal...")
    from scripts.download_via_api import ensure_chrome_debugging, get_templates

    ensure_chrome_debugging()
    with sync_playwright() as p:
        templates = get_templates(p, date_str)

    log.info("Found %d templates", len(templates))

    # Step 2: Capture API token (one browser session)
    log.info("Capturing API token...")
    url, headers, base_query = load_api_token(date_str)
    log.info("Token: %s...", url[:80])

    # Step 3: Download all templates concurrently
    log.info(
        "Downloading %d templates with %d workers...", len(templates), args.workers
    )
    start = time.time()

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                download_single_template, url, headers, base_query, t, output_dir
            ): t
            for t in templates
        }

        for future in as_completed(futures):
            template = futures[future]
            try:
                code, rows = future.result()
                results[code] = rows
                if rows > 0:
                    log.info("  %s: %d rows", code, rows)
                elif rows == 0:
                    log.warning("  %s: empty", code)
                elif rows == -1:
                    log.warning("  %s: skipped (known broken)", code)
                else:
                    log.error("  %s: error", code)
            except Exception as e:
                log.error("  %s: exception %s", template.split(" - ")[0].strip(), e)

    elapsed = time.time() - start
    total_rows = sum(v for v in results.values() if v > 0)
    successful = sum(1 for v in results.values() if v > 0)
    skipped = sum(1 for v in results.values() if v == -1)
    empty = sum(1 for v in results.values() if v == 0)
    failed = sum(1 for v in results.values() if v < -1)

    log.info("=" * 60)
    log.info(
        "Done! %d success, %d empty, %d skipped, %d failed | %d rows in %.1fs",
        successful,
        empty,
        skipped,
        failed,
        total_rows,
        elapsed,
    )
    log.info("=" * 60)


if __name__ == "__main__":
    main()

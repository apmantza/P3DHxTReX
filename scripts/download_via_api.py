"""
scripts/download_via_api.py — Download P3DH data via Power BI Query Execution API.

Captures the MWCToken and query from the browser, then replays it
with different template filters and increased row limits.

Usage:
    .venv/Scripts/python scripts/download_via_api.py [--date 31/12/2025]
"""
from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
CDP_URL = "http://localhost:9222"
REPORT_URL = "https://edap-public.eba.europa.eu/Report/index/MTE2"


def _click_option_by_text(frame, text: str) -> None:
    """Click a visible Power BI dropdown option by its title/text."""
    frame.evaluate(
        """
        ([targetText]) => {
            const options = Array.from(document.querySelectorAll('[role="option"]'));
            const match = options.find((opt) => {
                const title = (opt.getAttribute('title') || '').trim();
                const body = (opt.textContent || '').trim();
                return title === targetText || body === targetText || body.includes(targetText);
            });
            if (!match) {
                throw new Error(`Option not found: ${targetText}`);
            }
            match.click();
        }
        """,
        [text],
    )


def _set_reference_date(frame, date_str: str) -> None:
    """Set the reference date without waiting on flaky virtualized clicks."""
    frame.locator('[aria-label="ReferenceDate"][role="combobox"]').click(no_wait_after=True)
    time.sleep(2)
    _click_option_by_text(frame, date_str)
    time.sleep(1)
    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    time.sleep(1)


def _set_template(frame, template: str) -> None:
    """Set the template slicer, using the built-in search box for virtualized lists."""
    dd = frame.locator('[aria-label="Template"][role="combobox"]')
    dd.click(no_wait_after=True)
    time.sleep(2)
    popup_id = dd.get_attribute("aria-controls")

    # Clear existing selection.
    select_all = frame.locator(f'#{popup_id} [role="option"][title="Select all"]')
    if select_all.get_attribute("aria-selected") != "true":
        select_all.click(no_wait_after=True)
        time.sleep(0.5)
    select_all.click(no_wait_after=True)
    time.sleep(1)

    # Search to avoid relying on virtual scrolling.
    search_input = frame.locator(f'#{popup_id} input[aria-label="Search"]')
    search_input.fill("")
    search_token = template.split(" - ")[0]
    search_input.fill(search_token)
    time.sleep(1.5)

    matched = False
    for opt in frame.locator(f'#{popup_id} [role="option"]').all():
        text = opt.text_content().strip()
        title = opt.get_attribute("title") or ""
        if template == text or template == title or search_token in text:
            opt.click(no_wait_after=True)
            matched = True
            break
    if not matched:
        raise RuntimeError(f"Template not found in slicer: {template}")

    time.sleep(1)
    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    time.sleep(1)


def ensure_chrome_debugging() -> None:
    """Start Chrome debugging if it is not already available."""
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=2):
            return
    except OSError:
        pass

    log.info("Launching Chrome debugging session...")
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "launch_chrome_debug.py")],
        check=True,
        cwd=PROJECT_ROOT,
    )
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", 9222), timeout=2):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError("Chrome debugging did not start")


def get_powerbi_frame(page, retries: int = 20):
    """Wait for the embedded Power BI iframe and return its frame."""
    for _ in range(retries):
        iframe = page.query_selector("iframe[src*=powerbi]")
        if iframe:
            frame = iframe.content_frame()
            if frame:
                return frame
        time.sleep(1)
    raise RuntimeError("Power BI iframe not available")


def get_available_dates(p) -> list[str]:
    """Read all available reference dates from the slicer."""
    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(10)

    frame = get_powerbi_frame(page)
    frame.locator('[aria-label="ReferenceDate"][role="combobox"]').click(no_wait_after=True)
    time.sleep(2)

    dates = []
    for opt in frame.locator('[role="option"]').all():
        text = opt.text_content().strip()
        if text and text != "Select all":
            dates.append(text)

    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    page.close()
    browser.close()
    return dates


def pick_latest_date(dates: list[str]) -> str:
    """Pick the latest dd/mm/yyyy date from the slicer values."""
    return max(dates, key=lambda value: datetime.strptime(value, "%d/%m/%Y"))


def date_to_folder_name(date_str: str) -> str:
    """Convert dd/mm/yyyy to yyyymmdd for output folders."""
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y%m%d")


def capture_token_and_query(p, date_str: str, template: str) -> dict:
    """Capture the API token and query from the browser."""
    from playwright.sync_api import sync_playwright

    captured = {}

    def handle_request(request):
        if "QueryExecution" in request.url:
            captured["url"] = request.url
            captured["headers"] = dict(request.headers)
            captured["post_data"] = request.post_data

    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.on("request", handle_request)
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(10)

    frame = get_powerbi_frame(page)

    # Set Ref Date
    _set_reference_date(frame, date_str)

    # Set Template
    _set_template(frame, template)

    # Go to report to trigger data load
    frame.locator('[aria-label="Page navigation . Click here to follow"]').first.click()
    time.sleep(10)

    page.close()
    return captured


def get_templates(p, date_str: str) -> list[str]:
    """Get list of available templates (scrolls through virtual list)."""
    from playwright.sync_api import sync_playwright

    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(10)

    frame = get_powerbi_frame(page)

    # Set Ref Date
    _set_reference_date(frame, date_str)

    # Open template dropdown and scroll to load all items
    dd = frame.locator('[aria-label="Template"][role="combobox"]')
    dd.click(no_wait_after=True)
    time.sleep(2)

    popup_id = dd.get_attribute("aria-controls")
    all_templates = set()

    import re
    for scroll_y in range(0, 10000, 200):
        frame.evaluate(f"""
            (() => {{
                const el = document.querySelector('#{popup_id} .scroll-content');
                if (el) el.scrollTop = {scroll_y};
            }})()
        """)
        time.sleep(0.3)

        for opt in frame.locator(f'#{popup_id} [role="option"]').all():
            text = opt.text_content().strip()
            if text and text != "Select all" and re.match(r"^K_", text):
                all_templates.add(text)

    frame.locator("body").click(position={"x": 10, "y": 10})

    page.close()
    browser.close()
    return sorted(all_templates)


def get_entities(p, date_str: str) -> list[str]:
    """Get list of available entity names for a reference date."""
    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(10)

    frame = get_powerbi_frame(page)
    _set_reference_date(frame, date_str)

    dd = frame.locator('[aria-label="ENT_NAM"][role="combobox"]')
    dd.click(no_wait_after=True)
    time.sleep(2)

    popup_id = dd.get_attribute("aria-controls")
    all_entities = set()
    for scroll_y in range(0, 5000, 150):
        frame.evaluate(
            f"""
            (() => {{
                const el = document.querySelector('#{popup_id} .scroll-content');
                if (el) el.scrollTop = {scroll_y};
            }})()
            """
        )
        time.sleep(0.25)
        for opt in frame.locator(f'#{popup_id} [role="option"]').all():
            text = opt.text_content().strip()
            if text and text != "Select all":
                all_entities.add(text)

    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    page.close()
    browser.close()
    return sorted(all_entities)


def modify_query(query_json: dict, template: str, max_rows: int = 100000) -> dict:
    """Modify the query to target a specific template with higher row limit."""
    query = json.loads(json.dumps(query_json))  # Deep copy

    # Find and update the template filter
    cmd = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    for where in cmd["Query"].get("Where", []):
        condition = where.get("Condition", {})
        if "In" in condition:
            expr = condition["In"]["Expressions"][0]
            if expr.get("Column", {}).get("Property") == "Template":
                condition["In"]["Values"] = [[{"Literal": {"Value": f"'{template}'"}}]]

    # Increase row limit
    if "Binding" in cmd:
        if "DataReduction" in cmd["Binding"]:
            if "Primary" in cmd["Binding"]["DataReduction"]:
                if "Window" in cmd["Binding"]["DataReduction"]["Primary"]:
                    cmd["Binding"]["DataReduction"]["Primary"]["Window"]["Count"] = max_rows

    return query


def execute_query(url: str, headers: dict, query: dict, retries: int = 5) -> dict:
    """Execute the query and return the response, with retries for slow templates."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(query), timeout=300)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt == retries:
                break
            wait_s = attempt * 2
            log.warning("  Query attempt %d/%d failed, retrying in %ss", attempt, retries, wait_s)
            time.sleep(wait_s)
    raise last_exc


def parse_response(data: dict) -> pd.DataFrame:
    """Parse the standard Power BI DSR response into the 9-column CSV shape."""
    result = data["results"][0]["result"]["data"]
    dsr = result["dsr"]["DS"][0]
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
                            val = val_str
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


def parse_partitioned_response(data: dict) -> pd.DataFrame:
    """Parse alternate response shapes like K_83.01 into a richer CSV shape."""
    result = data["results"][0]["result"]["data"]
    dsr = result["dsr"]["DS"][0]
    value_dicts = dsr.get("ValueDicts", {})

    def canonical_field(name: str) -> str | None:
        key = name.lower().replace("_", " ")
        mapping = {
            "entity name": "Entity",
            "ent nam": "Entity",
            "country": "Country",
            "module name": "Module",
            "cell": "Cell",
            "cellcode": "Cell",
            "open key": "OpenKey",
            "keydescriptor": "OpenKey",
            "template": "Template",
            "row": "Row",
            "row name": "RowName",
            "row label": "RowName",
            "column": "Column",
            "column name": "ColumnName",
            "column label": "ColumnName",
            "sheet": "Sheet",
            "headerlabel": "Sheet",
            "referencedate": "ReferenceDate",
            "reference date": "ReferenceDate",
        }
        return mapping.get(key)

    g_to_field: dict[int, str] = {}
    for sel in result["descriptor"]["Select"]:
        value = sel.get("Value", "")
        if isinstance(value, str) and value.startswith("G"):
            field = canonical_field(sel.get("NativeReferenceName") or sel.get("Name", "").split(".")[-1])
            if field:
                g_to_field[int(value[1:])] = field

    g_to_dn: dict[int, str] = {}

    def parse_value(raw):
        if isinstance(raw, str):
            raw = raw[:-1] if raw.endswith("D") else raw
            try:
                return float(raw)
            except Exception:
                return raw
        if isinstance(raw, (int, float)):
            return float(raw)
        return raw

    def resolve(g_idx: int, val):
        d_key = g_to_dn.get(g_idx)
        if d_key and d_key in value_dicts and isinstance(val, (int, float)):
            idx = int(val)
            if idx < len(value_dicts[d_key]):
                return value_dicts[d_key][idx]
        return val

    def register_schema(obj) -> None:
        for schema_item in obj.get("S", []):
            name = schema_item.get("N", "")
            if isinstance(name, str) and name.startswith("G") and "DN" in schema_item:
                g_to_dn[int(name[1:])] = schema_item["DN"]

    def extract_sh_context() -> dict[str, object]:
        ctx: dict[str, object] = {}
        for sh in dsr.get("SH", []):
            register_schema(sh)
            for key, values in sh.items():
                if key.startswith("DM"):
                    for item in values:
                        register_schema(item)
                        for item_key, item_val in item.items():
                            if item_key.startswith("G"):
                                field = g_to_field.get(int(item_key[1:]))
                                if field:
                                    ctx[field] = resolve(int(item_key[1:]), item_val)
        return ctx

    rows: list[dict[str, object]] = []

    def parse_level(obj, context, depth=0):
        if depth > 20:
            return
        register_schema(obj)
        ctx = dict(context)
        for key, val in obj.items():
            if key.startswith("G"):
                field = g_to_field.get(int(key[1:]))
                if field:
                    ctx[field] = resolve(int(key[1:]), val)

        if "X" in obj:
            for x in obj["X"]:
                if "M0" in x:
                    rows.append(
                        {
                            "Entity": ctx.get("Entity", ""),
                            "Country": ctx.get("Country", ""),
                            "Module": ctx.get("Module", ""),
                            "Cell": ctx.get("Cell", ""),
                            "OpenKey": ctx.get("OpenKey", ""),
                            "Template": ctx.get("Template", ""),
                            "Row": ctx.get("Row", ""),
                            "RowName": ctx.get("RowName", ""),
                            "Column": ctx.get("Column", ""),
                            "ColumnName": ctx.get("ColumnName", ""),
                            "Sheet": ctx.get("Sheet", ""),
                            "ReferenceDate": ctx.get("ReferenceDate", ""),
                            "FactValue": parse_value(x["M0"]),
                        }
                    )

        for m in obj.get("M", []):
            for key, values in m.items():
                if key.startswith("DM"):
                    for child in values:
                        parse_level(child, ctx, depth + 1)

    base_context = extract_sh_context()
    for ph in dsr.get("PH", []):
        register_schema(ph)
        for key, values in ph.items():
            if key.startswith("DM"):
                for child in values:
                    parse_level(child, base_context, 1)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame[frame["Cell"].astype(str).str.strip() != ""].copy()
    if "ReferenceDate" in frame.columns:
        frame["ReferenceDate"] = pd.to_datetime(frame["ReferenceDate"], unit="ms", errors="coerce").dt.strftime("%Y-%m-%d")
    return frame


def download_partitioned_template(
    url: str,
    headers: dict,
    base_query: dict,
    entities: list[str],
) -> pd.DataFrame:
    """Download a slow template by partitioning the query over entities."""
    frames: list[pd.DataFrame] = []
    for entity in entities:
        query = json.loads(json.dumps(base_query))
        cmd = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
        cmd["Query"].setdefault("Where", []).append(
            {
                "Condition": {
                    "In": {
                        "Expressions": [
                            {
                                "Column": {
                                    "Expression": {"SourceRef": {"Source": "d2"}},
                                    "Property": "ENT_NAM",
                                }
                            }
                        ],
                        "Values": [[{"Literal": {"Value": f"'{entity}'"}}]],
                    }
                }
            }
        )
        response_data = execute_query(url, headers, query, retries=2)
        frame = parse_partitioned_response(response_data)
        if not frame.empty:
            frames.append(frame)
            log.info("  Entity %s -> %d rows", entity, len(frame))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def template_to_filename(template: str) -> str:
    code = template.split(" - ")[0].strip()
    return f"{code}_data_points.csv"


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--template", default=None)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    ensure_chrome_debugging()

    # Step 0: resolve latest date if not provided
    log.info("Reading available dates...")
    with sync_playwright() as p:
        available_dates = get_available_dates(p)

    if not available_dates:
        log.error("No reference dates found")
        return

    date_str = args.date or pick_latest_date(available_dates)
    output_dir = Path(args.output_dir) / date_to_folder_name(date_str)
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Using reference date %s", date_str)

    # Step 1: Capture token and query
    log.info("Capturing API token from browser...")
    with sync_playwright() as p:
        seed_templates = get_templates(p, date_str)

    if not seed_templates:
        log.error("No templates found for %s", date_str)
        return

    seed_template = seed_templates[0]
    log.info("Using seed template %s", seed_template[:70])

    with sync_playwright() as p:
        captured = capture_token_and_query(p, date_str, seed_template)

    if not captured:
        log.error("Failed to capture API request")
        return

    url = captured["url"]
    headers = captured["headers"]
    original_query = json.loads(captured["post_data"])

    log.info(f"Token captured: {url[:80]}")

    # Step 2: Get template list
    log.info("Getting template list...")
    templates = seed_templates
    if args.template:
        templates = [t for t in templates if args.template in t]
        if not templates:
            log.error("No templates matched %s", args.template)
            return

    log.info(f"Found {len(templates)} templates")
    for t in templates:
        log.info(f"  {t[:70]}")

    entities: list[str] | None = None

    # Step 3: Download each template via API
    for i, template in enumerate(templates):
        filename = template_to_filename(template)
        output_path = output_dir / filename

        if output_path.exists():
            log.info(f"[{i+1}/{len(templates)}] Skipping {filename}")
            continue

        log.info(f"[{i+1}/{len(templates)}] {template[:60]}")

        try:
            if template.startswith("K_83.01"):
                log.info("  Using partitioned fallback for K_83.01")
                if entities is None:
                    with sync_playwright() as p:
                        entities = get_entities(p, date_str)
                with sync_playwright() as p:
                    special_capture = capture_token_and_query(p, date_str, template)
                special_query = json.loads(special_capture["post_data"])
                df = download_partitioned_template(
                    special_capture["url"],
                    special_capture["headers"],
                    special_query,
                    entities,
                )
            else:
                modified_query = modify_query(original_query, template, max_rows=100000)
                response_data = execute_query(url, headers, modified_query)
                df = parse_response(response_data)

            df.to_csv(output_path, index=False, encoding="utf-8-sig")
            log.info(f"  Saved: {len(df)} rows -> {filename}")

        except Exception as e:
            log.error(f"  Failed: {e}")

    log.info("Done!")


if __name__ == "__main__":
    main()

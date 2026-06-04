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
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import cast

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

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
    frame.locator('[aria-label="ReferenceDate"][role="combobox"]').click(
        no_wait_after=True
    )
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
        if template in (text, title) or search_token in text:
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


def get_powerbi_frame(page, retries: int = 60):
    """Wait for the embedded Power BI iframe and return its frame."""
    for i in range(retries):
        iframe = page.query_selector("iframe[src*=powerbi]")
        if iframe:
            frame = iframe.content_frame()
            if frame:
                return frame
            # iframe element exists but content_frame() not ready yet
            time.sleep(1)
        else:
            time.sleep(1)
        if i == retries - 1:
            # Last attempt: try direct iframe src navigation as fallback
            iframe_el = page.query_selector("iframe[src*=powerbi]")
            if iframe_el:
                src = iframe_el.get_attribute("src")
                if src:
                    log.warning(
                        "Power BI iframe content_frame() unavailable; trying direct navigation to %s",
                        src[:80],
                    )
                    iframe_page = page.context.new_page()
                    iframe_page.goto(src, wait_until="domcontentloaded")
                    time.sleep(10)
                    return iframe_page
    raise RuntimeError("Power BI iframe not available")


def get_available_dates(p) -> list[str]:
    """Read all available reference dates from the slicer."""
    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(20)

    frame = get_powerbi_frame(page)
    frame.locator('[aria-label="ReferenceDate"][role="combobox"]').click(
        no_wait_after=True
    )
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


# Known P3DH templates (last refreshed 2026-04-16). Used as fallback if browser discovery fails.
KNOWN_TEMPLATES = [
    "K_00.02 - Accompanying narrative CODIS",
    "K_01.00 - Template EU CAE1 – Exposures to crypto-assets",
    "K_02.00 - EU CCR1 – Analysis of CCR exposure by approach",
    "K_03.00 - EU CCR3 – Standardised approach – CCR exposures by regulator",
    "K_04.00 - EU CCR4 – IRB approach – CCR exposures by exposure class and",
    "K_05.00 - EU CCR5 – Composition of collateral for CCR exposures",
    "K_06.00 - EU CCR6 – Credit derivatives exposures",
    "K_07.00 - EU CCR7 – RWEA flow statements of CCR exposures under the IM",
    "K_08.00 - EU CCR8 – Exposures to CCPs",
    "K_09.01 - EU-SEC1 - Securitisation exposures in the non-trading book",
    "K_09.02 - EU-SEC2 - Securitisation exposures in the trading book",
    "K_09.03 - EU-SEC3 - Securitisation exposures in the non-trading book a",
    "K_09.04 - EU-SEC4 - Securitisation exposures in the non-trading book a",
    "K_09.05 - EU-SEC5 - Exposures securitised by the institution - Exposur",
    "K_10.00 - EU MR1 - Market risk under the standardised approach",
    "K_101.00 - Section 2- total exposures",
    "K_102.00 - Section 3 - Intra-Financial System Assets",
    "K_103.00 - Section 4 - Intra-Financial System Liabilities",
    "K_104.00 - Section 5 - Securities Outstanding",
    "K_105.00 - Section 6 - Payments made in the reporting year excluding i",
    "K_106.00 - Section 7 - Assets Under Custody",
    "K_108.00 - Section 9 - Trading Volume",
    "K_109.00 - Section 10 - Notional Amount of Over-the-Counter OTC Deriva",
    "K_11.00 - EU MR2-A - Market risk under the internal Model Approach (IM",
    "K_110.00 - Section 11 - Trading and Available-for-Sale Securities",
    "K_111.00 - Section 12 - Level 3 Assets",
    "K_112.00 - Section 13 - Cross-Jurisdictional Claims",
    "K_113.00 - Section 14 - Cross-Jurisdictional Liabilities",
    "K_12.00 - EU MR2-B - RWEA flow statements of market risk exposures unde",
    "K_13.00 - EU MR3 - IMA values for trading portfolios",
    "K_18.01 - EU CVA 1 – Credit valuation adjustment risk under the Reduce",
    "K_18.02 - EU CVA 2 – Credit valuation adjustment risk under the Full B",
    "K_18.03 - EU CVA3 – Credit valuation adjustment risk under the Standar",
    "K_18.04 - EU CVA4 – RWEA flow statements of credit valuation adjustmen",
    "K_19.01 - EU OR1 -Operational risk losses",
    "K_19.02 - EU OR2 - Business Indicator, components and subcomponents",
    "K_19.03 - EU OR3 - Operational risk own funds requirements and risk ex",
    "K_20.01 - EU AE1 - Encumbered and unencumbered assets",
    "K_20.02 - EU AE2 - Collateral received and own debt securities issued",
    "K_20.03 - EU AE3 - Sources   of  encumbrance",
    "K_21.01 - EU CR1: Performing and non-performing exposures and related",
    "K_21.02 - EU CR1-A: Maturity of exposures",
    "K_22.01 - EU CR2: Changes in the stock of non-performing loans and adv",
    "K_22.02 - EU CR2a: Changes in the stock of non-performing loans and ad",
    "K_23.00 - EU CR3 –  CRM techniques overview:  Disclosure of the use of",
    "K_24.00 - EU CR4 – standardised approach – Credit risk exposure and CR",
    "K_25.00 - EU CR5 – standardised approach",
    "K_26.00 - EU CR6 – IRB approach – Credit risk exposures by exposure cl",
    "K_26.01 - EU CR6-A – Scope of the use of IRB and SA approaches",
    "K_27.01 - EU CR7 – IRB approach – Effect on the RWEAs of credit deriva",
    "K_27.02 - EU CR7-A – IRB approach – Disclosure of the extent of the us",
    "K_28.00 - EU CR8 –  RWEA flow statements of credit risk exposures unde",
    "K_29.00 - EU CR9 –IRB approach – Back-testing of PD per exposure clas",
    "K_29.01 - EU CR9.1 – IRB approach – Back-testing of PD per exposure cl",
    "K_29.02 - EU CR10 –  Specialised lending and equity exposures under th",
    "K_30.01 - EU REM1 - Remuneration awarded for the financial year",
    "K_30.02 - EU REM2 - Special payments  to staff whose professional acti",
    "K_30.03 - EU REM3 - Deferred remuneration",
    "K_30.04 - EU REM4 - Remuneration of 1 million EUR or more per year",
    "K_30.05 - EU REM5 - Information on remuneration of staff whose profess",
    "K_41.00 - Template 1 - Banking book- Indicators of potential climate C",
    "K_42.00 - Template 2 - Banking book - Indicators of potential climate",
    "K_43.00 - Template 3 - Banking book - Indicators of potential climate",
    "K_44.00 - Template 4 - Banking book - Indicators of potential climate",
    "K_45.00 - Template 5 - Banking book - Indicators of potential climate",
    "K_46.00 - Template 6 - Summary of GAR KPIs",
    "K_47.00 - Template 7 - Mitigating actions: Assets for the calculation",
    "K_48.00 - Template 8 - GAR (%)",
    "K_49.01 - Template 9.1 - Mitigating actions: Assets for the calculatio",
    "K_49.02 - Template 9.2 - BTAR %",
    "K_49.03 - Template 9.3 - Summary table - BTAR %",
    "K_50.00 - Template 10 - Other climate change mitigating actions that a",
    "K_60.00 - EU OV1 – Overview of total risk exposure amounts",
    "K_61.00 - EU KM1 - Key metrics template",
    "K_62.01 - EU INS1 - Insurance participations",
    "K_62.02 - EU INS2 - Financial conglomerates information on own funds a",
    "K_63.01 - EU CMS1 – Comparison of modelled and standardised risk weigh",
    "K_63.02 - EU CMS2 – Comparison of modelled and standardised risk weigh",
    "K_64.01 - EU LI1 - Differences between the accounting scope and the sc",
    "K_64.03 - EU LI2 - Main sources of differences between regulatory expo",
    "K_65.00 - EU PV1: Prudent valuation adjustments (PVA)",
    "K_66.01 - EU CC1 - Composition of regulatory own funds",
    "K_66.02 - EU CC2 - reconciliation of regulatory own funds to balance s",
    "K_67.01 - EU CCyB1 - Geographical distribution of credit exposures rel",
    "K_67.02 - EU CCyB2 - Amount of institution-specific countercyclical ca",
    "K_68.00 - EU IRRBB1 - Interest rate risks of non-trading book activiti",
    "K_00.04 - Accompanying narrative IRRBBDIS",
    "K_70.00 - EU LR1 - LRSum: Summary reconciliation of accounting assets",
    "K_71.00 -  EU LR2 - LRCom: Leverage ratio common disclosure",
    "K_72.00 - EU LR3 - LRSpl: Split-up of on balance sheet exposures (excl",
    "K_73.00 - EU LIQ1 - Quantitative information of LCR",
    "K_74.00 - EU LIQ2: Net Stable Funding Ratio",
    "K_80.00 - EU CQ1: Credit quality of forborne exposures",
    "K_81.00 - EU CQ2: Quality of forbearance",
    "K_82.00 - EU CQ3: Credit quality of performing and non-performing expo",
    "K_83.01 - EU CQ4: Quality of non-performing exposures by geography",
    "K_84.01 - EU CQ5: Credit quality of loans and advances by industry",
    "K_85.00 - EU CQ6: Collateral valuation - loans and advances",
    "K_86.00 - EU CQ7: Collateral obtained by taking possession and executi",
    "K_87.00 - EU CQ8: Collateral obtained by taking possession and executi",
    "K_90.01 - EU KM2 - Key metrics - MREL and, where applicable, G-SII req",
    "K_91.00 - EU TLAC1 - Composition - MREL and, where applicable, G-SII r",
    "K_93.00 - EU ILAC - Internal loss absorbing capacity: internal MREL an",
    "K_95.00 - Creditor ranking - Entity that is not a resolution entity",
    "K_96.00 - EU TLAC2b: Creditor ranking - Entity that is not a resolutio",
    "K_97.00 - EU TLAC3 - creditor ranking - resolution entity",
    "K_98.00 - EU TLAC3b: creditor ranking - resolution entity",
]


def get_templates(p, date_str: str) -> list[str]:
    """Get list of available templates (scrolls through virtual list).
    Falls back to KNOWN_TEMPLATES if browser discovery fails.
    """
    try:
        return _get_templates_from_browser(p, date_str)
    except Exception as e:
        log.warning(
            "Browser template discovery failed: %s — using known template list", e
        )
        return list(KNOWN_TEMPLATES)


def _get_templates_from_browser(p, date_str: str) -> list[str]:
    """Get list of available templates by scrolling through the virtual dropdown."""
    import re

    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(20)

    frame = get_powerbi_frame(page)

    # Set Ref Date
    _set_reference_date(frame, date_str)

    # Open template dropdown and scroll to load all items
    dd = frame.locator('[aria-label="Template"][role="combobox"]')
    dd.click(no_wait_after=True)
    time.sleep(2)

    popup_id = dd.get_attribute("aria-controls")
    all_templates = set()

    for scroll_y in range(0, 10000, 200):
        frame.evaluate(f"""
            (() => {{
                const el = document.querySelector('#{popup_id} .scroll-content');
                if (el) el.scrollTop = {scroll_y};
            }})()
        """)
        time.sleep(0.3)

        for opt in frame.locator(f'#{popup_id} [role="option"]').all():
            try:
                text = opt.text_content(timeout=5000).strip()
            except Exception:
                continue
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
    time.sleep(20)

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

    # Increase all Power BI data reduction limits.
    # The captured visual query has both Primary.Window.Count and Secondary.Top.Count;
    # raising only Primary still leaves the visual capped/truncated.
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


def execute_query(
    url: str, headers: dict, query: dict, retries: int = 5, timeout: int = 300
) -> dict:
    """Execute the query and return the response, with retries for slow templates."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                url, headers=headers, data=json.dumps(query), timeout=timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt == retries:
                break
            wait_s = attempt * 2
            log.warning(
                "  Query attempt %d/%d failed, retrying in %ss",
                attempt,
                retries,
                wait_s,
            )
            time.sleep(wait_s)
    raise RuntimeError("Query execution failed") from last_exc


def _parse_data_shapes_response(dsr_data: dict) -> pd.DataFrame:
    """Parse the DataShapes response format (used by K_83.01 and other complex templates)."""
    import json as _json

    debug_path = PROJECT_ROOT / "data" / "raw" / "P3DH" / "_debug_datashapes.json"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    with open(debug_path, "w", encoding="utf-8") as f:
        _json.dump(dsr_data, f, ensure_ascii=False, indent=2)
    log.info("  Dumped DataShapes debug to %s", debug_path)

    rows: list[dict] = []
    for shape in dsr_data.get("DataShapes", []):
        tables = shape.get("Tables", []) if isinstance(shape, dict) else []
        for table in tables:
            if not isinstance(table, dict):
                continue
            columns = [
                col.get("DisplayName", col.get("Name", f"col{i}"))
                for i, col in enumerate(table.get("Columns", []))
            ]
            for row in table.get("Rows", []):
                if isinstance(row, list):
                    rows.append(dict(zip(columns, row, strict=False)))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def parse_response(data: dict) -> pd.DataFrame:
    """Parse the standard Power BI DSR response into the 9-column CSV shape."""
    result = data["results"][0]["result"]["data"]
    dsr_data = result["dsr"]

    if "DS" not in dsr_data:
        log.warning(
            "  Response has no 'DS' key in DSR, keys: %s", list(dsr_data.keys())
        )
        if "DataShapes" in dsr_data:
            return _parse_data_shapes_response(dsr_data)
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
            field = canonical_field(
                sel.get("NativeReferenceName") or sel.get("Name", "").split(".")[-1]
            )
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

    parsed_frame = pd.DataFrame(rows)
    if parsed_frame.empty:
        return parsed_frame
    parsed_frame = parsed_frame[
        parsed_frame["Cell"].astype(str).str.strip() != ""
    ].copy()
    if "ReferenceDate" in parsed_frame.columns:
        converted_dates = pd.to_datetime(
            parsed_frame["ReferenceDate"], unit="ms", errors="coerce"
        )
        parsed_frame["ReferenceDate"] = [
            value.strftime("%Y-%m-%d") if pd.notna(value) else None
            for value in converted_dates
        ]
    return cast(pd.DataFrame, parsed_frame)


def download_partitioned_template(
    url: str,
    headers: dict,
    base_query: dict,
    entities: list[str],
) -> pd.DataFrame:
    """Download a slow template by partitioning the query over entities."""
    frames: list[pd.DataFrame] = []
    for i, entity in enumerate(entities):
        query = json.loads(json.dumps(base_query))
        cmd = query["queries"][0]["Query"]["Commands"][0][
            "SemanticQueryDataShapeCommand"
        ]
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
        response_data = execute_query(url, headers, query, retries=1)
        try:
            frame = parse_response(response_data)
        except (KeyError, IndexError, TypeError):
            try:
                frame = parse_partitioned_response(response_data)
            except Exception:
                frame = pd.DataFrame()
        if not frame.empty:
            frames.append(frame)
            log.info(
                "  [%d/%d] Entity %s -> %d rows",
                i + 1,
                len(entities),
                entity,
                len(frame),
            )
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

    # Step 1: Get template list from browser
    log.info("Discovering templates from browser...")
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

    # Known slow/large templates that need longer timeouts or partitioning
    SLOW_TEMPLATES = {"K_83.01"}
    LARGE_TIMEOUT = 600  # 10 minutes for slow templates

    # Step 3: Download each template via API
    modified_query = {}
    for i, template in enumerate(templates):
        template_code = template.split(" - ")[0].strip()
        filename = template_to_filename(template)
        output_path = output_dir / filename

        log.info(f"[{i + 1}/{len(templates)}] {template[:60]}")

        modified_query = modify_query(original_query, template, max_rows=100000)
        try:
            timeout = LARGE_TIMEOUT if template_code in SLOW_TEMPLATES else 120
            response_data = execute_query(
                url, headers, modified_query, retries=3, timeout=timeout
            )
            # Try standard parser first, then partitioned parser as fallback
            df = pd.DataFrame()
            with suppress(Exception):
                df = parse_response(response_data)
            if df.empty:
                with suppress(Exception):
                    df = parse_partitioned_response(response_data)
            if df.empty:
                raise ValueError("Both parsers returned empty DataFrame")

            df.to_csv(output_path, index=False, encoding="utf-8-sig")
            log.info(f"  Saved: {len(df)} rows -> {filename}")

        except Exception as e:
            log.warning(f"  Standard download failed: {e}")

            # Fallback: partition by entity for slow/large/failed templates
            log.info("  Attempting entity-partitioned fallback...")
            try:
                if entities is None:
                    with sync_playwright() as p:
                        entities = get_entities(p, date_str)
                    log.info(f"  Found {len(entities)} entities for partitioning")
                df = download_partitioned_template(
                    url, headers, modified_query, entities
                )
                if not df.empty:
                    df.to_csv(output_path, index=False, encoding="utf-8-sig")
                    log.info(f"  Saved via partitioned: {len(df)} rows -> {filename}")
                else:
                    log.error(
                        f"  Partitioned fallback returned empty for {template_code}"
                    )
            except Exception as e2:
                log.error(f"  Partitioned fallback also failed: {e2}")

    log.info("Done!")


if __name__ == "__main__":
    main()

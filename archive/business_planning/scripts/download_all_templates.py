"""
scripts/download_all_templates.py — Download all templates from EBA EDAP Data Points.

Each template: fresh page → set filters → go to report → hover → export.
The ... menu is at viewport coords (972, 337).

Usage:
    .venv/Scripts/python scripts/download_all_templates.py [--date 31/12/2025]
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
CDP_URL = "http://localhost:9222"
REPORT_URL = "https://edap-public.eba.europa.eu/Report/index/MTE2"

# Coordinates of the ... menu on the data table visual
MENU_X, MENU_Y = 972, 337


def get_frame(page):
    return page.query_selector("iframe[src*=powerbi]").content_frame()


def set_filter(frame, label: str, value: str):
    """Set a slicer filter."""
    dd = frame.locator(f'[aria-label="{label}"][role="combobox"]')
    dd.click()
    time.sleep(2)

    if label == "Template":
        popup_id = dd.get_attribute("aria-controls")
        select_all = frame.locator(f'#{popup_id} [role="option"][title="Select all"]')
        # Ensure all selected first, then deselect all
        if select_all.get_attribute("aria-selected") != "true":
            select_all.click()
            time.sleep(0.5)
        select_all.click()
        time.sleep(1)

    for opt in frame.locator('[role="option"]').all():
        if value in opt.text_content():
            opt.click()
            break

    time.sleep(1)
    frame.locator("body").click(position={"x": 10, "y": 10})
    time.sleep(1)


def download_template(p, date_str: str, template: str, output_path: Path):
    """Open fresh page, set filters, export, save."""
    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].new_page()
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    time.sleep(10)

    frame = get_frame(page)

    # Set filters
    set_filter(frame, "ReferenceDate", date_str)
    set_filter(frame, "Template", template)

    # Go to report
    frame.locator('[aria-label="Page navigation . Click here to follow"]').first.click()
    time.sleep(8)

    # Hover to reveal ... menu, then click
    page.mouse.move(MENU_X, MENU_Y)
    time.sleep(1)
    page.mouse.click(MENU_X, MENU_Y)
    time.sleep(2)

    # Click Export data
    frame.locator('button:has-text("Export data")').first.click()
    time.sleep(2)

    # Select "Data with current layout"
    frame.locator("pbi-radio-button:has-text('Data with current layout')").first.click()
    time.sleep(1)

    # Click Export and save
    with page.expect_download(timeout=60000) as dl:
        frame.locator('button:has-text("Export")').first.click()

    dl.value.save_as(str(output_path))
    log.info("  Saved: %s", output_path.name)

    page.close()


def template_to_filename(template: str) -> str:
    code = template.split(" - ")[0].strip()
    return f"{code}_data_points.xlsx"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="31/12/2025")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    # Step 1: Get template list
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].new_page()
        page.goto(REPORT_URL, wait_until="domcontentloaded")
        time.sleep(10)
        frame = get_frame(page)

        set_filter(frame, "ReferenceDate", args.date)

        dd = frame.locator('[aria-label="Template"][role="combobox"]')
        dd.click()
        time.sleep(2)
        templates = []
        for opt in frame.locator('[role="option"]').all():
            text = opt.text_content().strip()
            if text and text != "Select all" and re.match(r'^K_', text):
                templates.append(text)
        frame.locator("body").click(position={"x": 10, "y": 10})
        page.close()
        browser.close()

    log.info("Found %d templates", len(templates))
    for t in templates:
        log.info("  %s", t[:70])

    # Step 2: Download each
    for i, template in enumerate(templates):
        filename = template_to_filename(template)
        output_path = output_dir / filename

        if output_path.exists():
            log.info("[%d/%d] Skipping %s", i + 1, len(templates), filename)
            continue

        log.info("[%d/%d] %s", i + 1, len(templates), template[:60])
        try:
            with sync_playwright() as p:
                download_template(p, args.date, template, output_path)
        except Exception as e:
            log.error("  Failed: %s", e)

    log.info("Done!")


if __name__ == "__main__":
    main()

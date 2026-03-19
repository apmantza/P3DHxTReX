"""
scripts/download_data_points.py — Download Data Points Report from EBA EDAP.

Uses Playwright to connect to running Chrome via CDP and interact with
the Power BI embedded report (cross-origin iframe).

Flow:
    1. Connect to Chrome
    2. Find EDAP Data Points page
    3. Read current filters from Power BI
    4. Click Export via the EDAP page menu
    5. Save downloaded file

Usage:
    .venv/Scripts/python scripts/download_data_points.py [--output path.xlsx]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
P3DH_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"


def download(output: Path = None) -> Path | None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")

        # Find EDAP page
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "edap" in pg.url.lower() and "MTE2" in pg.url:
                    page = pg
                    break

        if not page:
            print("ERROR: Data Points Report not open. Navigate to it first.")
            browser.close()
            return None

        # Read filters from Power BI iframe
        try:
            iframe = page.frame_locator("iframe[src*='powerbi']")
            body = iframe.locator("body").inner_text(timeout=10000)
            for line in body.split("\n"):
                if "Template" in line:
                    idx = body.index("Template")
                    after = body[idx:idx+200].split("\n")
                    if len(after) > 1:
                        print(f"Current template: {after[1].strip()[:80]}")
                    break
        except Exception:
            print("Could not read Power BI filters")

        # Click ellipsis menu on EDAP page
        print("Opening report menu...")
        try:
            page.locator(".fa-ellipsis-v").click(timeout=5000)
            time.sleep(0.5)

            # Click Export to Data Point
            print("Looking for export option...")
            export_option = None
            for text in ["Export to Data Point", "Export", "Download", "Excel"]:
                try:
                    el = page.locator(f"text='{text}'").first
                    if el.is_visible(timeout=1000):
                        export_option = el
                        print(f"Found: {text}")
                        break
                except Exception:
                    continue

            if export_option:
                with page.expect_download(timeout=30000) as dl_info:
                    export_option.click()
                download = dl_info.value

                if output:
                    download.save_as(str(output))
                    print(f"Saved to: {output}")
                else:
                    dest = P3DH_DIR / download.suggested_filename
                    download.save_as(str(dest))
                    print(f"Saved to: {dest}")
                    output = dest
            else:
                # Show what's available
                items = page.locator(".dropdown-item, .dropdown-menu *").all()
                print("Available menu items:")
                for item in items:
                    try:
                        if item.is_visible(timeout=500):
                            print(f"  - {item.inner_text()[:50]}")
                    except Exception:
                        pass

        except Exception as e:
            print(f"Export error: {e}")
            # Fallback: take screenshot to see state
            page.screenshot(path=str(P3DH_DIR / "_export_debug.png"))
            print(f"Debug screenshot saved")

        browser.close()
        return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()
    output = Path(args.output) if args.output else None
    download(output)


if __name__ == "__main__":
    main()

"""
modules/fetch/edap_playwright.py — EDAP automation using Playwright.

Handles the Power BI embedded reports that chrome-cdp can't access due to
cross-origin iframe restrictions. Playwright connects to the same Chrome
instance via CDP but can interact with iframes natively.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
P3DH_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
TREX_DIR = PROJECT_ROOT / "data" / "raw" / "TrEx2025"

EDAP_URL = "https://edap-public.eba.europa.eu/"
DATA_POINTS_URL = "https://edap-public.eba.europa.eu/Report/index/MTE2"


@dataclass
class DownloadTarget:
    """A specific Power BI report to download."""
    reference_date: str = "31/12/2025"
    template: str = "K_02.00 - EU CCR1 - Analysis of CCR exposure by approach"
    is_current: str = "1"
    module_filter: str = "is not P3DH"
    status: str = "Accepted"
    output_filename: str = "data_points.xlsx"
    output_dir: Path = P3DH_DIR


class EdapPlaywrightFetcher:
    """Fetch data from EBA EDAP via Playwright (handles Power BI iframes)."""

    def __init__(self, cdp_url: str = "http://localhost:9222"):
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser = None

    def connect(self):
        """Connect to running Chrome via CDP."""
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
        log.info("Connected to Chrome via Playwright")

    def disconnect(self):
        """Close Playwright connection."""
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _find_edap_page(self):
        """Find the EDAP Data Points Report page."""
        for ctx in self._browser.contexts:
            for page in ctx.pages:
                if "edap-public" in page.url.lower() and "MTE2" in page.url:
                    return page
        return None

    def _get_powerbi_frame(self, page):
        """Get the Power BI iframe from the EDAP page."""
        return page.frame_locator('iframe[src*="powerbi"]')

    def ensure_report_open(self):
        """Open the Data Points Report if not already open."""
        page = self._find_edap_page()
        if page:
            log.info("Data Points Report already open")
            return page

        # Open new page
        page = self._browser.contexts[0].new_page()
        page.goto(DATA_POINTS_URL, wait_until="domcontentloaded")
        time.sleep(5)
        log.info("Opened Data Points Report")
        return page

    def get_report_text(self, page=None) -> str:
        """Get visible text from the Power BI report."""
        if page is None:
            page = self.ensure_report_open()

        iframe = self._get_powerbi_frame(page)
        try:
            body = iframe.locator("body")
            return body.inner_text(timeout=15000)
        except Exception as e:
            log.error("Failed to get report text: %s", e)
            return ""

    def get_current_filters(self, page=None) -> dict:
        """Extract current filter values from the report."""
        text = self.get_report_text(page)
        filters = {}

        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line in ("Entity Name", "Module Name", "Template", "Row", "Column", "Entity Code"):
                if i + 1 < len(lines):
                    value = lines[i + 1].strip()
                    filters[line] = value
                    i += 2
                    continue
            i += 1

        return filters

    def click_export(self, page=None, wait_for_download: bool = True) -> Path | None:
        """Click the export button and wait for download."""
        if page is None:
            page = self.ensure_report_open()

        iframe = self._get_powerbi_frame(page)

        log.info("Looking for export button...")

        # Try various selectors for the export button
        selectors = [
            'button[title*="Export" i]',
            'button[aria-label*="Export" i]',
            '[class*="export"]',
            'button:has-text("Export")',
            'button:has-text("Download")',
        ]

        for sel in selectors:
            try:
                btn = iframe.locator(sel).first
                if btn and btn.is_visible(timeout=3000):
                    log.info("Found export button: %s", sel)

                    if wait_for_download:
                        with page.expect_download(timeout=30000) as download_info:
                            btn.click()
                        download = download_info.value
                        log.info("Download started: %s", download.suggested_filename)
                        return download.path()
                    else:
                        btn.click()
                        return None
            except Exception:
                continue

        # Fallback: try clicking by text
        try:
            export_text = iframe.locator("text=Export").first
            if export_text and export_text.is_visible(timeout=2000):
                log.info("Found Export text, clicking...")
                if wait_for_download:
                    with page.expect_download(timeout=30000) as download_info:
                        export_text.click()
                    download = download_info.value
                    return download.path()
                else:
                    export_text.click()
                    return None
        except Exception as e:
            log.error("Export button not found: %s", e)

        return None

    def download_report(self, target: DownloadTarget, page=None) -> Path | None:
        """Download a report with specific filters."""
        if page is None:
            page = self.ensure_report_open()

        # Set filters (if different from current)
        self._set_filters(page, target)

        # Click export
        download_path = self.click_export(page, wait_for_download=True)

        if download_path:
            # Save to output directory
            output = target.output_dir / target.output_filename
            import shutil
            shutil.copy2(download_path, output)
            log.info("Saved to %s", output)
            return output

        return None

    def _set_filters(self, page, target: DownloadTarget):
        """Set filter values in the Power BI report."""
        iframe = self._get_powerbi_frame(page)

        # Reference Date filter
        self._set_slicer_filter(iframe, "Reference Date", target.reference_date)

        # Template filter
        self._set_slicer_filter(iframe, "Template", target.template)

    def _set_slicer_filter(self, iframe, filter_name: str, value: str):
        """Set a specific slicer filter value."""
        log.info("Setting filter '%s' = '%s'", filter_name, value)

        try:
            # Find the filter header
            header = iframe.locator(f'text="{filter_name}"').first
            if header and header.is_visible(timeout=3000):
                # Click the dropdown near this header
                parent = header.locator('..')
                dropdown = parent.locator('[class*="dropdown"], [role="combobox"], button').first
                if dropdown:
                    dropdown.click()
                    time.sleep(1)

                    # Find and click the option
                    option = iframe.locator(f'text="{value}"').first
                    if option and option.is_visible(timeout=3000):
                        option.click()
                        time.sleep(1)
                        log.info("Set filter '%s' to '%s'", filter_name, value)
                        return True
        except Exception as e:
            log.warning("Could not set filter '%s': %s", filter_name, e)

        return False


def create_fetcher(cdp_url: str = "http://localhost:9222") -> EdapPlaywrightFetcher:
    """Create a Playwright-based EDAP fetcher."""
    return EdapPlaywrightFetcher(cdp_url)

"""
modules/fetch/edap.py — Automate data downloads from EBA EDAP Public Portal.

Portal structure (discovered 2026-03-19):
  - Transparency → 2025 → Time series, Capital, Credit Risk, NPE, NACE
  - Pillar 3 Data HUB → stress test disclosures
  - Public Access → direct data downloads

Uses chrome-cdp-skill to interact with the live Chrome session.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import modules.fetch.cdp_wrapper as cdp

log = logging.getLogger(__name__)

EDAP_URL = "https://edap-public.eba.europa.eu/"
PROJECT_ROOT = Path(__file__).parent.parent.parent
P3DH_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
TREX_DIR = PROJECT_ROOT / "data" / "raw" / "TrEx2025"

# Actual report URLs from EDAP (discovered via --discover)
REPORT_URLS = {
    "tr_time_series": "https://edap-public.eba.europa.eu/Report/index/MjE=",
    "tr_capital":     "https://edap-public.eba.europa.eu/Report/index/MjI=",
    "tr_credit_risk": "https://edap-public.eba.europa.eu/Report/index/MjM=",
    "tr_npe":         "https://edap-public.eba.europa.eu/Report/index/MjQ=",
    "tr_nace":        "https://edap-public.eba.europa.eu/Report/index/MjU=",
}


@dataclass
class FetchConfig:
    """Configuration for what to download."""
    p3dh_period: str = "20251231"
    p3dh_categories: list[str] = None
    p3dh_save_dir: Path = P3DH_DIR
    trex_year: int = 2025
    trex_files: list[str] = None
    trex_save_dir: Path = TREX_DIR

    def __post_init__(self):
        if self.p3dh_categories is None:
            self.p3dh_categories = [
                "common_disclosures",
                "financial_disclosures",
                "irrbb_disclosures",
                "mrel_disclosures",
                "esg_disclosures",
                "renumeration_disclosures",
            ]
        if self.trex_files is None:
            self.trex_files = ["tr_cre", "tr_oth", "tr_sov", "tr_mrk"]


class EdapFetcher:
    """Fetch data from EBA EDAP portal via Chrome CDP."""

    def __init__(self, config: FetchConfig | None = None):
        self.config = config or FetchConfig()

    def ensure_portal_open(self) -> str:
        """Open EDAP portal tab if not already open. Returns target ID."""
        tab = cdp.find_tab("edap-public.eba.europa.eu")
        if tab:
            return tab["target_id"]

        log.info("Opening EDAP portal...")
        cdp.open_tab(EDAP_URL)
        time.sleep(4)

        tab = cdp.find_tab("edap-public.eba.europa.eu")
        if not tab:
            raise RuntimeError("Could not open EDAP portal tab")
        return tab["target_id"]

    def navigate(self, target: str, url: str) -> None:
        """Navigate to URL and wait for load."""
        cdp.navigate(target, url)
        time.sleep(2)
        self._wait_for_page(target)

    def _wait_for_page(self, target: str, timeout: int = 15) -> None:
        """Wait for page to be ready."""
        for _ in range(timeout):
            try:
                ready = cdp.eval_js(target, "document.readyState === 'complete'")
                if "true" in ready.lower():
                    return
            except Exception:
                pass
            time.sleep(1)

    def screenshot(self, target: str, name: str) -> Path:
        """Take a named screenshot."""
        path = self.config.p3dh_save_dir / f"_screenshot_{name}.png"
        cdp.screenshot(target, str(path))
        return path

    def navigate_to_transparency(self, target: str) -> None:
        """Navigate to Transparency Exercise section."""
        log.info("Navigating to Transparency Exercise...")
        # Click on "Transparency" link in nav
        cdp.eval_js(target, """
            (() => {
                const links = document.querySelectorAll('a');
                for (const a of links) {
                    if (a.textContent.trim() === 'Transparency') {
                        a.click();
                        return 'clicked Transparency';
                    }
                }
                return 'not found';
            })()
        """)
        time.sleep(2)

    def navigate_to_transparency_report(self, target: str, report: str) -> None:
        """Navigate to a specific transparency report (time_series, capital, etc.)."""
        url = REPORT_URLS.get(report)
        if url:
            log.info("Navigating to %s...", report)
            self.navigate(target, url)
        else:
            # Try clicking text
            cdp.eval_js(target, f"""
                (() => {{
                    const links = document.querySelectorAll('a');
                    for (const a of links) {{
                        const text = a.textContent.trim();
                        if (text === '{report.replace('_', ' ')}') {{
                            a.click();
                            return 'clicked: ' + text;
                        }}
                    }}
                    return 'not found';
                }})()
            """)
            time.sleep(2)

    def click_export_button(self, target: str, fmt: str = "xlsx") -> bool:
        """Click the export/download button. Returns True if found."""
        log.info("Looking for export button (%s)...", fmt)
        result = cdp.eval_js(target, """
            (() => {
                // Try various selectors for export buttons
                const selectors = [
                    'button[title*="export" i]',
                    'button[title*="download" i]',
                    'a[download]',
                    'button[class*="export" i]',
                    'button[class*="download" i]',
                    '.export-btn',
                    '.download-btn',
                ];

                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.click();
                        return 'clicked: ' + (el.textContent || el.title || '').trim().substring(0, 50);
                    }
                }

                // Try text-based
                const buttons = document.querySelectorAll('button, a');
                for (const btn of buttons) {
                    const text = (btn.textContent || '').toLowerCase().trim();
                    if (text.includes('export') || text.includes('download') || text.includes('csv') || text.includes('excel')) {
                        btn.click();
                        return 'clicked text: ' + btn.textContent.trim().substring(0, 50);
                    }
                }

                // Try icon buttons (might have SVG)
                const iconBtns = document.querySelectorAll('button svg, a svg');
                for (const svg of iconBtns) {
                    const btn = svg.closest('button, a');
                    if (btn) {
                        const title = btn.getAttribute('title') || '';
                        const ariaLabel = btn.getAttribute('aria-label') || '';
                        if (title.toLowerCase().includes('download') || ariaLabel.toLowerCase().includes('download')) {
                            btn.click();
                            return 'clicked icon: ' + title;
                        }
                    }
                }

                return 'no export button found';
            })()
        """)
        return "clicked" in result.lower()

    def set_filters(self, target: str, filters: dict) -> None:
        """Set filter values on the page."""
        for name, value in filters.items():
            log.info("Setting filter %s = %s", name, value)
            cdp.eval_js(target, f"""
                (() => {{
                    const inputs = document.querySelectorAll('input, select');
                    for (const el of inputs) {{
                        const elName = (el.name || el.id || '').toLowerCase();
                        if (elName.includes('{name.lower()}')) {{
                            if (el.tagName === 'SELECT') {{
                                for (const opt of el.options) {{
                                    if (opt.text.toLowerCase().includes('{str(value).lower()}')) {{
                                        el.value = opt.value;
                                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                        return 'selected: ' + opt.text;
                                    }}
                                }}
                            }} else {{
                                el.value = '{value}';
                                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                return 'set input: ' + el.name;
                            }}
                        }}
                    }}
                    return 'filter not found';
                }})()
            """)
            time.sleep(1)

    def get_available_options(self, target: str) -> dict:
        """Get all available filter/dropdown options on the page."""
        result = cdp.eval_js(target, """
            (() => {
                const result = {
                    url: window.location.href,
                    title: document.title,
                    selects: [],
                    inputs: [],
                    exportButtons: []
                };

                document.querySelectorAll('select').forEach(sel => {
                    const options = [];
                    sel.querySelectorAll('option').forEach(opt => {
                        if (opt.value) options.push({value: opt.value, text: opt.textContent?.trim()});
                    });
                    result.selects.push({name: sel.name || sel.id, options});
                });

                document.querySelectorAll('input').forEach(inp => {
                    result.inputs.push({
                        name: inp.name || inp.id,
                        type: inp.type,
                        placeholder: inp.placeholder
                    });
                });

                // Find export/download buttons
                document.querySelectorAll('button, a').forEach(btn => {
                    const text = (btn.textContent || '').toLowerCase();
                    const title = (btn.title || '').toLowerCase();
                    if (text.includes('export') || text.includes('download') ||
                        title.includes('export') || title.includes('download')) {
                        result.exportButtons.push({
                            text: btn.textContent?.trim(),
                            title: btn.title,
                            class: btn.className
                        });
                    }
                });

                return JSON.stringify(result);
            })()
        """)
        try:
            return json.loads(result)
        except Exception:
            return {"raw": result}

    def discover_portal_structure(self, target: str) -> dict:
        """Explore the full portal structure."""
        log.info("Discovering portal structure...")
        result = cdp.eval_js(target, """
            (() => {
                const result = {
                    url: window.location.href,
                    title: document.title,
                    links: [],
                    buttons: [],
                    inputs: [],
                    selects: []
                };

                document.querySelectorAll('a').forEach(a => {
                    const text = a.textContent?.trim();
                    if (text && text.length < 100 && text.length > 1) {
                        result.links.push({text, href: a.href});
                    }
                });

                document.querySelectorAll('button').forEach(btn => {
                    const text = btn.textContent?.trim();
                    if (text && text.length < 50) {
                        result.buttons.push(text);
                    }
                });

                document.querySelectorAll('input').forEach(inp => {
                    result.inputs.push({
                        name: inp.name || inp.id,
                        type: inp.type,
                        placeholder: inp.placeholder
                    });
                });

                document.querySelectorAll('select').forEach(sel => {
                    const options = [];
                    sel.querySelectorAll('option').forEach(opt => {
                        if (opt.value) options.push({value: opt.value, text: opt.textContent?.trim()});
                    });
                    result.selects.push({name: sel.name || sel.id, options});
                });

                return JSON.stringify(result);
            })()
        """)
        try:
            return json.loads(result)
        except Exception:
            return {"raw": result}


def create_fetcher(config: FetchConfig | None = None) -> EdapFetcher:
    """Create an EdapFetcher."""
    return EdapFetcher(config)

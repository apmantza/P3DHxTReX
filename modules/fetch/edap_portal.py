"""Access to the EBA EDAP Pillar 3 Data Hub (P3DH) report.

The P3DH Data Points report is an embedded Power BI report. A browser session sets the
reference date and template, and Playwright captures the QueryExecution request (URL,
headers, body). The request can then be replayed with other filters using plain HTTP.

Everything that needs a browser (token capture, listing dates, templates, entities)
is in this module. Discovery is strict: a failed discovery raises, it never falls back
to a stored list (a stale list of truncated template names once caused silent failures).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import requests
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

EDAP_URL = "https://edap-public.eba.europa.eu/"
REPORT_URL = "https://edap-public.eba.europa.eu/Report/index/MTE2"
HEADLESS = os.environ.get("P3DH_HEADLESS", "0") == "1"


def template_code(template: str) -> str:
    """'K_61.00 - EU KM1 - ...' -> 'K_61.00'."""
    return template.split(" - ")[0].strip()


def date_to_folder_name(date_str: str) -> str:
    """dd/mm/yyyy -> yyyymmdd."""
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _open_browser(p):
    browser = p.chromium.launch(headless=HEADLESS)
    return browser, browser.new_context()


def _click_option_by_text(frame, text: str) -> None:
    """Click a visible Power BI dropdown option by its title or text."""
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
    frame.locator('[aria-label="ReferenceDate"][role="combobox"]').click(no_wait_after=True)
    time.sleep(2)
    _click_option_by_text(frame, date_str)
    time.sleep(1)
    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    time.sleep(1)


def _set_template(frame, template: str) -> None:
    """Select one template with the slicer's search box (the list is virtualised)."""
    dd = frame.locator('[aria-label="Template"][role="combobox"]')
    dd.click(no_wait_after=True)
    time.sleep(2)
    popup_id = dd.get_attribute("aria-controls")

    select_all = frame.locator(f'#{popup_id} [role="option"][title="Select all"]')
    if select_all.get_attribute("aria-selected") != "true":
        select_all.click(no_wait_after=True)
        time.sleep(0.5)
    select_all.click(no_wait_after=True)
    time.sleep(1)

    search_input = frame.locator(f'#{popup_id} input[aria-label="Search"]')
    search_input.fill("")
    search_token = template_code(template)
    search_input.fill(search_token)
    time.sleep(1.5)

    for opt in frame.locator(f'#{popup_id} [role="option"]').all():
        text = opt.text_content().strip()
        title = opt.get_attribute("title") or ""
        if template in (text, title) or search_token in text:
            opt.click(no_wait_after=True)
            break
    else:
        raise RuntimeError(f"Template not found in slicer: {template}")

    time.sleep(1)
    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    time.sleep(1)


def open_report_from_portal(page) -> None:
    """Open the EDAP landing page first, then the report (a fresh tab can get a 403)."""
    page.goto(EDAP_URL, wait_until="domcontentloaded")
    time.sleep(5)
    page.goto(REPORT_URL, wait_until="domcontentloaded")


def get_powerbi_frame(page, retries: int = 60):
    """Wait for the embedded Power BI iframe and return its frame."""
    for _ in range(retries):
        iframe = page.query_selector("iframe[src*=powerbi]")
        if iframe:
            frame = iframe.content_frame()
            if frame:
                return frame
        time.sleep(1)
    raise RuntimeError("Power BI iframe not available")


def _read_slicer(frame, aria_label: str, scroll_step: int = 150, max_scroll: int = 60000,
                 settle_scrolls: int = 60, pause: float = 0.15) -> set[str]:
    """Read every option of a virtualised Power BI slicer by scrolling its list."""
    combo = frame.locator(f'[aria-label="{aria_label}"][role="combobox"]')
    combo.click(no_wait_after=True)
    time.sleep(2)
    popup_id = combo.get_attribute("aria-controls")
    found: set[str] = set()
    last, stable = -1, 0
    for scroll_y in range(0, max_scroll, scroll_step):
        frame.evaluate(
            f"""(() => {{
                const el = document.querySelector('#{popup_id} .scroll-content');
                if (el) el.scrollTop = {scroll_y};
            }})()"""
        )
        time.sleep(pause)
        for opt in frame.locator(f'#{popup_id} [role="option"]').all():
            try:
                text = (opt.text_content(timeout=5000) or "").strip()
            except Exception:  # noqa: BLE001 - option scrolled away while reading
                continue
            if text and text != "Select all":
                found.add(text)
        stable = stable + 1 if len(found) == last else 0
        last = len(found)
        if scroll_y > 3000 and stable > settle_scrolls:
            break
    frame.locator("body").click(position={"x": 10, "y": 10}, no_wait_after=True)
    return found


def _report_frame(p):
    browser, ctx = _open_browser(p)
    page = ctx.new_page()
    open_report_from_portal(page)
    time.sleep(20)
    return browser, page, get_powerbi_frame(page)


def get_available_dates(p) -> list[str]:
    """Reference dates listed by the portal (dd/mm/yyyy)."""
    browser, page, frame = _report_frame(p)
    try:
        dates = sorted(_read_slicer(frame, "ReferenceDate", settle_scrolls=3),
                       key=lambda d: datetime.strptime(d, "%d/%m/%Y"))
    finally:
        browser.close()
    if not dates:
        raise RuntimeError("portal returned no reference dates")
    return dates


def get_templates(p, date_str: str) -> list[str]:
    """Templates the portal lists for a reference date. Raises if the list is implausible."""
    browser, page, frame = _report_frame(p)
    try:
        _set_reference_date(frame, date_str)
        found = {t for t in _read_slicer(frame, "Template", scroll_step=200, settle_scrolls=10)
                 if re.match(r"^K_\d", t)}
    finally:
        browser.close()
    if len(found) < 30:
        raise RuntimeError(f"template discovery looks incomplete ({len(found)} templates)")
    return sorted(found)


def get_entities(p, date_str: str) -> list[str]:
    """Entity names listed for a reference date (can be incomplete; see download docs)."""
    browser, page, frame = _report_frame(p)
    try:
        _set_reference_date(frame, date_str)
        found = _read_slicer(frame, "ENT_NAM", scroll_step=150, settle_scrolls=60)
    finally:
        browser.close()
    if len(found) < 50:
        raise RuntimeError(f"entity discovery looks incomplete ({len(found)} entities)")
    return sorted(found)


def capture_token_and_query(p, date_str: str, template: str) -> dict[str, Any]:
    """Capture URL, headers and body of the report's fact query for a date and template."""
    captured: dict[str, Any] = {}

    def handle_request(request):
        if "QueryExecution" in request.url and request.post_data:
            body = request.post_data
            # keep the fact query (it has the cell dimension), not slicer queries
            if "CellCode" in body and "FactValue" in body and "RestartTokens" not in body:
                captured["url"] = request.url
                captured["headers"] = dict(request.headers)
                captured["post_data"] = body

    browser, ctx = _open_browser(p)
    try:
        page = ctx.new_page()
        page.on("request", handle_request)
        open_report_from_portal(page)
        time.sleep(10)
        frame = get_powerbi_frame(page)
        _set_reference_date(frame, date_str)
        _set_template(frame, template)
        frame.locator('[aria-label="Page navigation . Click here to follow"]').first.click()
        time.sleep(10)
        page.close()
    finally:
        browser.close()
    return captured


# ---------------------------------------------------------------------------
# HTTP replay
# ---------------------------------------------------------------------------

class QueryError(RuntimeError):
    """Query failed; carries the HTTP status and the start of the response body."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def execute_query(url: str, headers: dict, query: dict, retries: int = 3, timeout: int = 300) -> dict:
    """POST a QueryExecution request. Retries timeouts, connection errors, 429 and 5xx.

    `retries` is the number of attempts. A 4xx response (other than 429) is not retried;
    401/403 mean the token expired.
    """
    last: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(query), timeout=timeout)
        except requests.RequestException as exc:  # timeouts, connection and decoding errors
            last = QueryError(f"{type(exc).__name__}: {str(exc)[:120]}")
        else:
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    last = QueryError("HTTP 200 with a body that is not JSON", 200, resp.text[:200])
            else:
                last = QueryError(f"HTTP {resp.status_code}", resp.status_code, resp.text[:300])
                if resp.status_code < 500 and resp.status_code != 429:
                    raise last
        if attempt < retries:
            time.sleep(min(30, 2 ** attempt))
    raise last if last else QueryError("query failed")


class RateLimiter:
    """Process-wide request spacing shared by worker threads."""

    def __init__(self, max_requests_per_minute: int):
        self.min_interval = 60.0 / max_requests_per_minute if max_requests_per_minute > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                time.sleep(self._next_at - now)
                now = time.monotonic()
            self._next_at = now + self.min_interval


def polite_delay(delay_ms: int, limiter: RateLimiter | None = None) -> None:
    if limiter is not None:
        limiter.wait()
    if delay_ms > 0:
        time.sleep((delay_ms / 1000) * random.uniform(0.5, 1.5))


class TokenManager:
    """Holds the captured URL, headers and base query and refreshes them when they age."""

    def __init__(self, date_str: str, seed_template: str, refresh_minutes: int = 8):
        self.date_str = date_str
        self.seed_template = seed_template
        self.refresh_after = timedelta(minutes=refresh_minutes)
        self.url = ""
        self.headers: dict[str, str] = {}
        self.base_query: dict[str, Any] = {}
        self.refreshed_at = datetime.min

    def refresh(self) -> None:
        log.info("Refreshing Power BI token and query capture...")
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                with sync_playwright() as p:
                    captured = capture_token_and_query(p, self.date_str, self.seed_template)
                if not captured:
                    raise RuntimeError("no fact query captured from the report")
                self.url = captured["url"]
                self.headers = dict(captured["headers"])
                self.base_query = json.loads(captured["post_data"])
                self.refreshed_at = datetime.now()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("Token refresh attempt %d/3 failed: %s", attempt, exc)
                time.sleep(10 * attempt)
        raise RuntimeError("Failed to refresh the Power BI token") from last_exc

    def ensure_fresh(self) -> None:
        if not self.url or datetime.now() - self.refreshed_at > self.refresh_after:
            self.refresh()

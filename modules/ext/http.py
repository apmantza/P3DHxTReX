"""HTTP for the external statistics. It runs curl, which checks certificates with the store of the operating system.
The certificate check of Python fails for Eurostat in this setup, and switching the check off is not an option."""

from __future__ import annotations

import subprocess
import time

RETRY_WAITS = (5, 20, 60)  # seconds to wait before each new try after a server error or a failed transfer


class NoData(Exception):
    """The source has no series for the request (HTTP 404)."""


def _once(url: str, timeout: int) -> str:
    p = subprocess.run(["curl", "-sS", "-L", "-m", str(timeout), "-A", "Mozilla/5.0", "-w", "\n%{http_code}", url], capture_output=True, timeout=timeout + 30)
    if p.returncode != 0:
        raise RuntimeError(f"curl failed ({p.returncode}): {p.stderr.decode('utf-8', 'replace')[:200]}")
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n")
    code = code.strip()
    if code == "404":
        raise NoData(url)
    if not code.startswith("2"):
        raise RuntimeError(f"HTTP {code} for {url}: {body[:200]}")
    return body


def fetch(url: str, timeout: int = 300, waits: tuple[int, ...] = RETRY_WAITS) -> str:
    """The body of the URL. A server error (5xx), a timeout, or a failed transfer is tried again after each wait in waits. A 404 is not tried again."""
    for wait in (*waits, None):
        try:
            return _once(url, timeout)
        except NoData:
            raise
        except (RuntimeError, subprocess.TimeoutExpired):
            if wait is None:
                raise
            time.sleep(wait)
    raise RuntimeError("unreachable")

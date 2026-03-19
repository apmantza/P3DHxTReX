"""
modules/fetch/cdp_wrapper.py — Python wrapper around chrome-cdp-skill.

Thin wrapper that calls cdp.mjs commands via subprocess.
All commands return parsed output (strings, dicts, bytes).

Uses the automation Chrome profile from scripts/launch_chrome_debug.py.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_CDP_SCRIPT = Path(__file__).parent.parent.parent / ".chrome-cdp-skill" / "skills" / "chrome-cdp" / "scripts" / "cdp.mjs"

# Use the automation Chrome profile
_CHROME_DEBUG_PROFILE = Path(__file__).parent.parent.parent / ".chrome-debug-profile"
_CDP_PORT_FILE = _CHROME_DEBUG_PROFILE / "DevToolsActivePort"


def _run(cmd: list[str], timeout: int = 60) -> str:
    """Run a cdp.mjs command and return stdout."""
    full = ["node", str(_CDP_SCRIPT)] + cmd
    log.debug("cdp: %s", " ".join(full))

    # Set env to use our automation Chrome profile
    env = os.environ.copy()
    if _CDP_PORT_FILE.exists():
        env["CDP_PORT_FILE"] = str(_CDP_PORT_FILE)

    result = subprocess.run(
        full,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cdp command failed: {result.stderr.strip()}")
    return result.stdout.strip()


def list_tabs() -> list[dict]:
    """List all open Chrome tabs. Returns list of {targetId, url, title}."""
    output = _run(["list"])
    tabs = []
    for line in output.splitlines():
        if not line.strip():
            continue
        # Format: "TARGETID  Title                                                    URL"
        # The target ID is at the start, URL is at the end
        line = line.strip()
        if len(line) < 10:
            continue

        # Find the URL (starts with http)
        url_start = line.find("http")
        if url_start > 0:
            url = line[url_start:].strip()
            before_url = line[:url_start].strip()
            # target_id is the first word (8 chars)
            parts = before_url.split(None, 1)
            target_id = parts[0] if parts else before_url[:8]
            title = parts[1].strip() if len(parts) > 1 else ""
        else:
            parts = line.split(None, 2)
            target_id = parts[0] if parts else ""
            url = parts[1] if len(parts) > 1 else ""
            title = parts[2] if len(parts) > 2 else ""

        tabs.append({
            "target_id": target_id,
            "url": url,
            "title": title,
        })
    return tabs


def find_tab(url_fragment: str) -> dict | None:
    """Find an open tab whose URL contains the fragment."""
    for tab in list_tabs():
        if url_fragment.lower() in tab["url"].lower():
            return tab
    return None


def open_tab(url: str) -> str:
    """Open a new tab with the given URL. Returns targetId."""
    return _run(["open", url])


def navigate(target: str, url: str) -> str:
    """Navigate tab to URL and wait for load."""
    return _run(["nav", target, url])


def click(target: str, selector: str) -> str:
    """Click element by CSS selector."""
    return _run(["click", target, selector])


def type_text(target: str, text: str) -> str:
    """Type text at focused element."""
    return _run(["type", target, text])


def eval_js(target: str, expression: str, timeout: int = 30) -> str:
    """Evaluate JavaScript in page context. Returns result as string."""
    return _run(["eval", target, expression], timeout=timeout)


def get_html(target: str, selector: str | None = None) -> str:
    """Get full page HTML or scoped to selector."""
    cmd = ["html", target]
    if selector:
        cmd.append(selector)
    return _run(cmd)


def screenshot(target: str, file: str | Path | None = None) -> str:
    """Take screenshot. Returns path to saved file."""
    cmd = ["shot", target]
    if file:
        cmd.append(str(file))
    return _run(cmd)


def snap(target: str) -> str:
    """Get accessibility tree snapshot."""
    return _run(["snap", target])


def wait_for_selector(target: str, selector: str, timeout_ms: int = 10000) -> bool:
    """Wait for selector to appear. Returns True if found."""
    js = f"""
    (async () => {{
        const start = Date.now();
        while (Date.now() - start < {timeout_ms}) {{
            if (document.querySelector('{selector}')) return true;
            await new Promise(r => setTimeout(r, 500));
        }}
        return false;
    }})()
    """
    result = eval_js(target, js, timeout=timeout_ms // 1000 + 5)
    return "true" in result.lower()


def scroll_down(target: str, pixels: int = 500) -> str:
    """Scroll down by given pixels."""
    return eval_js(target, f"window.scrollBy(0, {pixels})")


def set_input_value(target: str, selector: str, value: str) -> str:
    """Set input value via JS (more reliable than typing)."""
    js = f"""
    (() => {{
        const el = document.querySelector('{selector}');
        if (el) {{
            el.value = '{value}';
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        return !!el;
    }})()
    """
    return eval_js(target, js)

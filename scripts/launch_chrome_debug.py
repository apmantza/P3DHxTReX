"""
scripts/launch_chrome_debug.py — Launch Chrome with remote debugging enabled.

Launches Chrome with flags that:
- Enable remote debugging on port 9222
- Use a dedicated profile for automation
- No first-run dialogs

Usage:
    .venv/Scripts/python scripts/launch_chrome_debug.py [--kill] [--headless]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CHROME_PATHS = [
    Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
]

CHROME_PROFILE_DIR = PROJECT_ROOT / ".chrome-debug-profile"
DEBUG_PORT = 9222


def find_chrome() -> Path:
    """Find Chrome executable."""
    for path in CHROME_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError("Chrome not found")


def kill_chrome() -> None:
    """Kill Chrome instances."""
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                   capture_output=True, shell=True)
    time.sleep(1)


def is_debugging_ready(port: int = DEBUG_PORT) -> bool:
    """Check if Chrome remote debugging is responding."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except (ConnectionRefusedError, socket.timeout):
        return False


def create_devtools_port_file() -> None:
    """Fetch the WebSocket URL from Chrome and write DevToolsActivePort."""
    try:
        data = urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=5).read()
        info = json.loads(data)
        ws_url = info["webSocketDebuggerUrl"]

        # Parse: ws://localhost:9222/devtools/browser/xxx
        parts = ws_url.replace("ws://", "").split("/", 1)
        port = parts[0].split(":")[1]
        path = "/" + parts[1]

        port_file = CHROME_PROFILE_DIR / "DevToolsActivePort"
        with open(port_file, "w") as f:
            f.write(f"{port}\n{path}\n")
        return
    except Exception as e:
        print(f"Warning: Could not create DevToolsActivePort: {e}")


def launch_chrome(headless: bool = False) -> subprocess.Popen:
    """Launch Chrome with remote debugging enabled."""
    chrome_exe = find_chrome()
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    flags = [
        str(chrome_exe),
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--disable-sync",
        "--disable-extensions",
        "--remote-allow-origins=*",
        "--disable-infobars",
    ]

    if headless:
        flags.append("--headless=new")

    proc = subprocess.Popen(
        flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for Chrome to start
    for _ in range(15):
        if is_debugging_ready():
            create_devtools_port_file()
            return proc
        time.sleep(1)

    proc.kill()
    raise TimeoutError("Chrome did not start in time")


def main():
    parser = argparse.ArgumentParser(description="Launch Chrome with remote debugging")
    parser.add_argument("--kill", action="store_true", help="Kill existing Chrome first")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--check", action="store_true", help="Only check if debugging is ready")
    args = parser.parse_args()

    if args.check:
        if is_debugging_ready():
            print(f"Chrome debugging is ready on port {DEBUG_PORT}")
            create_devtools_port_file()
        else:
            print(f"Chrome debugging NOT ready on port {DEBUG_PORT}")
        return

    if args.kill:
        print("Killing existing Chrome instances...")
        kill_chrome()

    if is_debugging_ready():
        print(f"Chrome debugging already ready on port {DEBUG_PORT}")
        create_devtools_port_file()
        return

    print("Launching Chrome with remote debugging...")
    proc = launch_chrome(headless=args.headless)
    print(f"Chrome PID: {proc.pid}")
    print(f"Profile dir: {CHROME_PROFILE_DIR}")
    print(f"Debug port: {DEBUG_PORT}")
    print(f"\nYou can now run: .venv/Scripts/python scripts/fetch_edap_data.py --discover")


if __name__ == "__main__":
    main()

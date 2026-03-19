"""
scripts/test_cdp.py — Test Chrome CDP connection.

Run this after enabling Chrome remote debugging.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import modules.fetch.cdp_wrapper as cdp

print("Testing Chrome CDP connection...")

try:
    tabs = cdp.list_tabs()
    print(f"Found {len(tabs)} open tabs:")
    for tab in tabs[:10]:
        print(f"  {tab['target_id'][:8]}  {tab['url'][:60]}  {tab.get('title', '')[:40]}")
except RuntimeError as e:
    print(f"ERROR: {e}")
    print("\nTo fix:")
    print("1. Open Chrome")
    print("2. Go to chrome://inspect/#remote-debugging")
    print("3. Toggle the switch ON")

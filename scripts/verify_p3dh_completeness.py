"""Verify P3DH download completeness by checking portal via CDP/Playwright."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.download_via_api import get_available_dates, get_entities, get_templates


def main():
    from playwright.sync_api import sync_playwright

    date_str = "31/12/2025"

    print(f"=== Verifying P3DH completeness for {date_str} ===\n")

    # 1. Get available dates from portal
    print("Discovering available dates from portal...")
    with sync_playwright() as p:
        dates = get_available_dates(p)
    print(f"  Available dates: {dates}")
    if date_str not in dates:
        print(f"  WARNING: {date_str} not found in available dates!")
    else:
        print(f"  ✓ {date_str} is available")

    # 2. Get templates from portal
    print(f"\nDiscovering templates for {date_str}...")
    with sync_playwright() as p:
        portal_templates = get_templates(p, date_str)
    print(f"  Portal templates: {len(portal_templates)}")
    for t in portal_templates:
        print(f"    {t}")

    # 3. Get entities from portal
    print(f"\nDiscovering entities for {date_str}...")
    with sync_playwright() as p:
        portal_entities = get_entities(p, date_str)
    print(f"  Portal entities: {len(portal_entities)}")
    for e in portal_entities[:20]:
        print(f"    {e}")
    if len(portal_entities) > 20:
        print(f"    ... and {len(portal_entities) - 20} more")

    # 4. Compare with downloaded files
    raw_dir = PROJECT_ROOT / "data" / "raw" / "P3DH" / "20251231"
    downloaded_codes = set()
    if raw_dir.exists():
        for f in raw_dir.glob("*_data_points.csv"):
            code = f.name.split("_")[0] + "_" + f.name.split("_")[1]
            downloaded_codes.add(code)

    portal_codes = {t.split(" - ")[0].strip() for t in portal_templates}

    missing = portal_codes - downloaded_codes
    extra = downloaded_codes - portal_codes

    print("\n=== Comparison ===")
    print(f"  Portal templates:     {len(portal_codes)}")
    print(f"  Downloaded templates: {len(downloaded_codes)}")

    if missing:
        print(f"\n  MISSING from download ({len(missing)}):")
        for code in sorted(missing):
            # Find full template name
            full = next((t for t in portal_templates if t.startswith(code)), code)
            print(f"    {full}")
    else:
        print("\n  ✓ All portal templates downloaded")

    if extra:
        print(f"\n  EXTRA in download ({len(extra)}):")
        for code in sorted(extra):
            print(f"    {code}")

    # 5. Save report
    report = {
        "date": date_str,
        "portal_dates": dates,
        "portal_templates": portal_templates,
        "portal_entity_count": len(portal_entities),
        "portal_entities": portal_entities,
        "downloaded_codes": sorted(downloaded_codes),
        "missing_codes": sorted(missing),
        "extra_codes": sorted(extra),
    }
    report_path = PROJECT_ROOT / "data" / "p3dh_verification_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Report saved to: {report_path}")


if __name__ == "__main__":
    main()

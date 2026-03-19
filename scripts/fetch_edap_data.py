"""
scripts/fetch_edap_data.py — CLI to download data from EBA EDAP via Chrome CDP.

Usage:
    .venv/Scripts/python scripts/fetch_edap_data.py [--period 20251231] [--category common] [--trex] [--discover]

Options:
    --period YYYYMMDD   P3DH reporting period to download
    --category NAME     Specific P3DH category
    --all               Download all categories for the period
    --trex              Download TrEx transparency exercise files
    --discover          Explore portal structure and print available options
    --dry-run           Show what would be downloaded without downloading
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fetch_edap")


def load_download_targets() -> dict:
    """Load download targets from config."""
    import yaml
    config_path = PROJECT_ROOT / "config" / "download_targets.yaml"
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def discover_portal(fetcher) -> None:
    """Explore and print portal structure."""
    target = fetcher.ensure_portal_open()
    log.info("EDAP portal tab: %s", target)

    # Get page structure
    structure = fetcher.discover_portal_structure(target)
    print("\n" + "=" * 60)
    print("PORTAL STRUCTURE")
    print("=" * 60)
    print(json.dumps(structure, indent=2, default=str))
    print("=" * 60)


def download_p3dh(fetcher, period: str, categories: list[str], settings: dict) -> list[Path]:
    """Download P3DH files for a period."""
    from modules.fetch.edap import P3DH_DIR

    target = fetcher.ensure_portal_open()
    delay = settings.get("download_delay", 5)
    downloaded = []

    for category in categories:
        log.info("Downloading %s for %s...", category, period)

        # Navigate to data points
        fetcher.navigate_to_data_points(target)

        # Apply filters
        fetcher.filter_by_period(target, period)
        fetcher.filter_by_template(target, category)

        # Screenshot state
        if settings.get("keep_screenshots", True):
            ss_path = P3DH_DIR / f"_state_{period}_{category}.png"
            fetcher.screenshot(target, ss_path)

        # Export
        fetcher.click_export(target, "xlsx")
        downloaded.append(P3DH_DIR / f"{period}_{category}.xlsx")

        time.sleep(delay)

    return downloaded


def download_trex(fetcher, config, settings: dict) -> list[Path]:
    """Download TrEx files."""
    from modules.fetch.edap import TREX_DIR

    target = fetcher.ensure_portal_open()
    delay = settings.get("download_delay", 5)
    downloaded = []

    fetcher.navigate_to_transparency_exercise(target)

    for file_key in config.trex_files:
        log.info("Downloading %s...", file_key)
        fetcher.filter_by_template(target, file_key)
        fetcher.click_export(target, "csv")
        downloaded.append(TREX_DIR / f"{file_key}.csv")
        time.sleep(delay)

    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Download EBA EDAP data via Chrome CDP")
    parser.add_argument("--period", default="20251231", help="P3DH reporting period (YYYYMMDD)")
    parser.add_argument("--category", help="Specific P3DH category to download")
    parser.add_argument("--all", action="store_true", help="Download all categories")
    parser.add_argument("--trex", action="store_true", help="Download TrEx files")
    parser.add_argument("--discover", action="store_true", help="Explore portal structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    args = parser.parse_args()

    from modules.fetch.edap import FetchConfig, EdapFetcher, P3DH_DIR, TREX_DIR

    targets = load_download_targets()
    config = FetchConfig(
        p3dh_period=args.period,
        p3dh_save_dir=P3DH_DIR,
        trex_save_dir=TREX_DIR,
    )

    fetcher = EdapFetcher(config)

    if args.discover:
        discover_portal(fetcher)
        return

    # Show what would happen
    categories = config.p3dh_categories
    if args.category:
        categories = [args.category]

    if args.dry_run:
        print(f"Period: {args.period}")
        print(f"P3DH categories: {categories}")
        if args.trex:
            print(f"TrEx files: {config.trex_files}")
        return

    # Connect to Chrome
    log.info("Checking Chrome connection...")
    target = fetcher.ensure_portal_open()
    log.info("Connected to EDAP portal: %s", target)

    # Download
    all_downloaded = []
    settings = targets.get("settings", {})

    if not args.trex or args.all:
        all_downloaded.extend(download_p3dh(fetcher, args.period, categories, settings))

    if args.trex or args.all:
        all_downloaded.extend(download_trex(fetcher, config, settings))

    log.info("Downloaded %d files", len(all_downloaded))
    for f in all_downloaded:
        log.info("  %s", f)


if __name__ == "__main__":
    main()

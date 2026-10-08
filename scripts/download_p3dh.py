"""Download P3DH templates with the verified DSR decoder.

Examples:
  .venv/Scripts/python scripts/download_p3dh.py --date "31/12/2025" --template K_61.00 K_60.00
  .venv/Scripts/python scripts/download_p3dh.py --date "30/06/2026" --all

Output (one row per fact, exact DPM cell codes):
  data/raw/P3DH/<yyyymmdd>/K_xx.xx_data_points.csv
  data/raw/P3DH_json/<yyyymmdd>/K_xx.xx.jsonl.gz   (raw responses, for re-decoding)
  data/runs/p3dh/<yyyymmdd>_manifest_v2.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.fetch import edap_portal as portal  # noqa: E402
from modules.fetch.p3dh_fetch import (  # noqa: E402
    Fetcher, Manifest, download_template, write_outputs,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("download_p3dh")

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
JSON_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH_json"
RUN_DIR = PROJECT_ROOT / "data" / "runs" / "p3dh"

# The portal query for these templates exceeds the server limit of 225 seconds,
# even for one entity (error rsQueryTimeoutExceeded). Use --include-slow to try again.
SLOW_TEMPLATES = {"K_83.01"}


def load_live_cache(path: Path) -> list[str] | None:
    """Return a discovery cache only if it was written by live portal discovery."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("source") != "live":
        log.warning("Ignoring %s: not marked as live discovery", path.name)
        return None
    return payload["values"]


def save_live_cache(path: Path, values: list[str], date: str, kind: str) -> None:
    payload = {"date": date, "kind": kind, "source": "live", "count": len(values),
               "updated_at": datetime.now().isoformat(timespec="seconds"), "values": values}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock() -> Path | None:
    """One downloader at a time: two runs would overwrite each other's manifest entries."""
    lock = RUN_DIR / "download.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
        except ValueError:
            pid = 0
        if pid and _pid_alive(pid):
            log.error("Another downloader is running (PID %s). Lock file: %s", pid, lock)
            return None
    lock.write_text(str(os.getpid()))
    return lock


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Reference date dd/mm/yyyy")
    ap.add_argument("--template", nargs="*", default=[], help="Template codes, e.g. K_61.00")
    ap.add_argument("--all", action="store_true", help="All templates the portal lists for the date")
    ap.add_argument("--force", action="store_true", help="Download complete templates again")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Retry templates marked failed_server or partial")
    ap.add_argument("--include-slow", action="store_true",
                    help=f"Also try templates known to time out: {sorted(SLOW_TEMPLATES)}")
    ap.add_argument("--batch-size", type=int, default=80, help="Entities per request (fallback only)")
    ap.add_argument("--workers", type=int, default=4, help="Parallel requests (fallback only)")
    ap.add_argument("--cross-check", type=int, default=3,
                    help="Entities re-fetched by name to compare with the paged result (0 = off)")
    ap.add_argument("--max-requests-per-minute", type=int, default=60)
    ap.add_argument("--request-delay-ms", type=int, default=100)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--refresh-minutes", type=int, default=8)
    ap.add_argument("--refresh-discovery", action="store_true",
                    help="List templates and entities from the portal again")
    args = ap.parse_args()
    if not args.all and not args.template:
        ap.error("give --all or --template CODE [CODE ...]")
    if args.include_slow:
        args.timeout = max(args.timeout, 300)  # the server error arrives after 225 seconds

    folder = portal.date_to_folder_name(args.date)
    date_iso = datetime.strptime(args.date, "%d/%m/%Y").strftime("%Y-%m-%d")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock()
    if lock is None:
        return 3
    try:
        return run(args, folder, date_iso)
    finally:
        lock.unlink(missing_ok=True)


def run(args, folder: str, date_iso: str) -> int:
    manifest = Manifest(RUN_DIR / f"{folder}_manifest_v2.json")

    tpl_cache, ent_cache = RUN_DIR / f"{folder}_templates.json", RUN_DIR / f"{folder}_entities.json"
    templates = None if args.refresh_discovery else load_live_cache(tpl_cache)
    if templates is None:
        with sync_playwright() as p:
            available = portal.get_available_dates(p)
            if args.date not in available:
                log.error("%s is not an available reference date: %s", args.date, available)
                return 2
            templates = portal.get_templates(p, args.date)
        save_live_cache(tpl_cache, templates, args.date, "templates")
    log.info("%s: %d templates", args.date, len(templates))

    def get_entities() -> list[str]:
        """List entities from the portal. Only the fallback path needs this."""
        cached = None if args.refresh_discovery else load_live_cache(ent_cache)
        if cached is None:
            with sync_playwright() as p:
                cached = portal.get_entities(p, args.date)
            save_live_cache(ent_cache, cached, args.date, "entities")
        return cached

    wanted = set(args.template)
    missing = wanted - {portal.template_code(t) for t in templates}
    if missing:
        log.error("Templates not listed for %s: %s", args.date, sorted(missing))
        return 2
    todo = []
    for tpl in templates:
        code = portal.template_code(tpl)
        if not args.all and code not in wanted:
            continue
        if code in SLOW_TEMPLATES and not args.include_slow:
            if not manifest.get(code):
                manifest.update(code, {"status": "skipped_slow", "template": tpl,
                                       "detail": "server query timeout (225 s); use --include-slow"})
            continue
        prior = manifest.get(code).get("status")
        if prior in ("complete", "empty") and not args.force:
            continue
        if prior in {"failed_server", "partial"} and not args.retry_failed and not wanted:
            continue
        todo.append(tpl)
    log.info("%d templates to download", len(todo))
    if not todo:
        return 0

    token = portal.TokenManager(args.date, todo[0], args.refresh_minutes)
    token.refresh()
    fetcher = Fetcher(token, portal.RateLimiter(args.max_requests_per_minute), portal.execute_query,
                      portal.polite_delay, args.request_delay_ms, args.timeout, args.retries)

    bad = refresh_failures = 0
    for tpl in todo:
        code = portal.template_code(tpl)
        log.info("== %s", tpl)
        prior = manifest.get(code)
        try:
            result = download_template(fetcher, tpl, code, get_entities, date_iso,
                                       args.batch_size, args.workers,
                                       cross_check_sample=args.cross_check)
            if result["status"] != "complete" and prior.get("status") == "complete":
                # keep the good files and the good manifest entry; record the failed attempt
                prior["last_failed_attempt"] = {
                    "status": result["status"], "at": datetime.now().isoformat(timespec="seconds"),
                    "detail": result["stats"].get("detail") or result["stats"].get("template_level")}
                manifest.update(code, prior)
                log.warning("   %s: new attempt is %s; kept the earlier complete files", code,
                            result["status"])
                bad += 1
                continue
            entry = {"status": result["status"], "template": tpl, **result["stats"],
                     "failed": result["failed"][:50], "truncated": result["truncated"][:50]}
            if result["rows"]:
                entry.update(write_outputs(result, code, folder, date_iso, RAW_DIR, JSON_DIR))
            manifest.update(code, entry)
            log.info("   %s: %s rows=%s entities=%s requests=%s %ss", code, result["status"],
                     entry.get("rows"), entry.get("entities_with_rows"),
                     result["stats"]["requests"], result["stats"]["seconds"])
            bad += result["status"] not in ("complete", "empty")
        except Exception as exc:  # noqa: BLE001
            log.exception("   %s failed: %s", code, exc)
            if prior.get("status") == "complete":
                prior["last_failed_attempt"] = {"status": "error", "detail": str(exc)[:200],
                                                "at": datetime.now().isoformat(timespec="seconds")}
                manifest.update(code, prior)
            else:
                manifest.update(code, {"status": "error", "template": tpl, "detail": str(exc)[:200]})
            bad += 1
            refresh_failures += "refresh" in str(exc).lower()
            if refresh_failures >= 2:
                log.error("Token refresh failed twice; stopping the run")
                break
    log.info("done: %d of %d templates not complete", bad, len(todo))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

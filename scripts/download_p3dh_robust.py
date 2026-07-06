"""Robust P3DH downloader with resume, token refresh, and entity workers."""

from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from threading import Lock
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.download_via_api import (  # noqa: E402
    capture_token_and_query,
    date_to_folder_name,
    ensure_chrome_debugging,
    execute_query,
    get_entities,
    get_templates,
    modify_query,
    parse_partitioned_response,
    parse_response,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "P3DH"
RUN_DIR = PROJECT_ROOT / "data" / "runs" / "p3dh"
BROKEN_TEMPLATES = {"K_83.01"}


def template_code(template: str) -> str:
    return template.split(" - ")[0].strip()


def template_filename(template: str) -> str:
    return f"{template_code(template)}_data_points.csv"


def has_restart_token(response_data: dict[str, Any]) -> bool:
    try:
        datasets = response_data["results"][0]["result"]["data"]["dsr"].get("DS", [])
    except (KeyError, IndexError, TypeError):
        return False
    return any(bool(ds.get("RT")) for ds in datasets if isinstance(ds, dict))


def parse_any_response(response_data: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame()
    try:
        frame = parse_response(response_data)
    except Exception:
        frame = pd.DataFrame()
    if frame.empty:
        try:
            frame = parse_partitioned_response(response_data)
        except Exception:
            frame = pd.DataFrame()
    return frame


class TokenManager:
    def __init__(self, date_str: str, seed_template: str, refresh_minutes: int):
        self.date_str = date_str
        self.seed_template = seed_template
        self.refresh_after = timedelta(minutes=refresh_minutes)
        self.url = ""
        self.headers: dict[str, str] = {}
        self.base_query: dict[str, Any] = {}
        self.refreshed_at = datetime.min
        self.request_count = 0

    def refresh(self) -> None:
        log.info("Refreshing Power BI token/query capture...")
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                ensure_chrome_debugging()
                with sync_playwright() as p:
                    captured = capture_token_and_query(
                        p, self.date_str, self.seed_template
                    )
                if not captured:
                    raise RuntimeError(
                        "Failed to capture Power BI QueryExecution request"
                    )
                self.url = captured["url"]
                self.headers = dict(captured["headers"])
                self.base_query = json.loads(captured["post_data"])
                self.refreshed_at = datetime.now()
                self.request_count = 0
                log.info("Token refreshed: %s...", self.url[:80])
                return
            except Exception as exc:
                last_exc = exc
                wait_s = 10 * attempt
                log.warning(
                    "Token refresh attempt %d/3 failed: %s; retrying in %ss",
                    attempt,
                    exc,
                    wait_s,
                )
                time.sleep(wait_s)
        raise RuntimeError(
            "Failed to refresh Power BI token after retries"
        ) from last_exc

    def ensure_fresh(self) -> None:
        if not self.url or datetime.now() - self.refreshed_at > self.refresh_after:
            self.refresh()

    def mark_request(self) -> None:
        self.request_count += 1


def add_in_filter(
    query: dict[str, Any], source: str, property_name: str, value: str
) -> None:
    cmd = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    escaped = value.replace("'", "''")
    cmd["Query"].setdefault("Where", []).append(
        {
            "Condition": {
                "In": {
                    "Expressions": [
                        {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": source}},
                                "Property": property_name,
                            }
                        }
                    ],
                    "Values": [[{"Literal": {"Value": f"'{escaped}'"}}]],
                }
            }
        }
    )


def entity_query(base_query: dict[str, Any], entity: str) -> dict[str, Any]:
    query = json.loads(json.dumps(base_query))
    add_in_filter(query, "d1", "ENT_NAM", entity)
    return query


def entity_row_query(
    base_query: dict[str, Any], entity: str, row_code: str
) -> dict[str, Any]:
    query = entity_query(base_query, entity)
    add_in_filter(query, "d6", "Row", row_code)
    return query


def entity_open_key_query(
    base_query: dict[str, Any], entity: str, open_key: str
) -> dict[str, Any]:
    query = entity_query(base_query, entity)
    add_in_filter(query, "d4", "KeyDescriptor", open_key)
    return query


def entity_column_query(
    base_query: dict[str, Any], entity: str, column_code: str
) -> dict[str, Any]:
    query = entity_query(base_query, entity)
    add_in_filter(query, "d7", "Column", column_code)
    return query


def entity_row_column_query(
    base_query: dict[str, Any], entity: str, row_code: str, column_code: str
) -> dict[str, Any]:
    query = entity_row_query(base_query, entity, row_code)
    add_in_filter(query, "d7", "Column", column_code)
    return query


def extract_open_keys(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "Row" not in frame.columns:
        return []
    keys = []
    for value in frame["Row"].dropna().astype(str).unique().tolist():
        if " = " in value or " | " in value:
            keys.append(value)
    return sorted(keys)


def extract_column_codes(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "Column" not in frame.columns:
        return []
    values = []
    for value in frame["Column"].dropna().astype(str).unique().tolist():
        if value and value.lower() != "nan":
            values.append(value)
    return sorted(values)


def dictionary_row_codes(template: str) -> list[str]:
    path = PROJECT_ROOT / "data" / "processed" / "p3dh_data_dictionary.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    codes = (
        df.loc[df["template_code"] == template_code(template), "row_code"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )
    return sorted(code for code in codes if code and not code.startswith("OPEN_"))


class RateLimiter:
    """Simple process-local global rate limiter shared by worker threads."""

    def __init__(self, max_requests_per_minute: int):
        self.min_interval = 0.0
        if max_requests_per_minute > 0:
            self.min_interval = 60.0 / max_requests_per_minute
        self._lock = Lock()
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


def polite_delay(delay_ms: int, rate_limiter: RateLimiter | None = None) -> None:
    if rate_limiter is not None:
        rate_limiter.wait()
    if delay_ms <= 0:
        return
    jitter = random.uniform(0.5, 1.5)
    time.sleep((delay_ms / 1000) * jitter)


def fetch_entity_partition(
    url: str,
    headers: dict[str, str],
    template_query: dict[str, Any],
    entity: str,
    timeout: int,
    retries: int,
    request_delay_ms: int,
    rate_limiter: RateLimiter | None,
) -> tuple[str, pd.DataFrame, bool, str | None]:
    try:
        polite_delay(request_delay_ms, rate_limiter)
        response = execute_query(
            url,
            headers,
            entity_query(template_query, entity),
            retries=retries,
            timeout=timeout,
        )
        frame = parse_any_response(response)
        return entity, frame, has_restart_token(response), None
    except Exception as exc:
        return entity, pd.DataFrame(), False, str(exc)


def fetch_entity_dimension_partition(
    url: str,
    headers: dict[str, str],
    template_query: dict[str, Any],
    entity: str,
    dimension_value: str,
    dimension: str,
    timeout: int,
    retries: int,
    request_delay_ms: int,
    rate_limiter: RateLimiter | None,
) -> tuple[str, str, str, pd.DataFrame, bool, str | None]:
    try:
        polite_delay(request_delay_ms, rate_limiter)
        if dimension == "open_key":
            query = entity_open_key_query(template_query, entity, dimension_value)
        elif dimension == "column":
            query = entity_column_query(template_query, entity, dimension_value)
        else:
            raise ValueError(f"Unsupported dimension fallback: {dimension}")
        response = execute_query(url, headers, query, retries=retries, timeout=timeout)
        frame = parse_any_response(response)
        return (
            entity,
            dimension_value,
            dimension,
            frame,
            has_restart_token(response),
            None,
        )
    except Exception as exc:
        return entity, dimension_value, dimension, pd.DataFrame(), False, str(exc)


def fetch_entity_row_column_partition(
    url: str,
    headers: dict[str, str],
    template_query: dict[str, Any],
    entity: str,
    row_code: str,
    column_code: str,
    timeout: int,
    retries: int,
    request_delay_ms: int,
    rate_limiter: RateLimiter | None,
) -> tuple[str, str, str, pd.DataFrame, bool, str | None]:
    try:
        polite_delay(request_delay_ms, rate_limiter)
        response = execute_query(
            url,
            headers,
            entity_row_column_query(template_query, entity, row_code, column_code),
            retries=retries,
            timeout=timeout,
        )
        frame = parse_any_response(response)
        return entity, row_code, column_code, frame, has_restart_token(response), None
    except Exception as exc:
        return entity, row_code, column_code, pd.DataFrame(), False, str(exc)


def fetch_entity_open_key_partition(
    url: str,
    headers: dict[str, str],
    template_query: dict[str, Any],
    entity: str,
    open_key: str,
    timeout: int,
    retries: int,
    request_delay_ms: int,
    rate_limiter: RateLimiter | None,
) -> tuple[str, str, pd.DataFrame, bool, str | None]:
    try:
        polite_delay(request_delay_ms, rate_limiter)
        response = execute_query(
            url,
            headers,
            entity_open_key_query(template_query, entity, open_key),
            retries=retries,
            timeout=timeout,
        )
        frame = parse_any_response(response)
        return entity, open_key, frame, has_restart_token(response), None
    except Exception as exc:
        return entity, open_key, pd.DataFrame(), False, str(exc)


def fetch_entity_row_partition(
    url: str,
    headers: dict[str, str],
    template_query: dict[str, Any],
    entity: str,
    row_code: str,
    timeout: int,
    retries: int,
    request_delay_ms: int,
    rate_limiter: RateLimiter | None,
) -> tuple[str, str, pd.DataFrame, bool, str | None]:
    try:
        polite_delay(request_delay_ms, rate_limiter)
        response = execute_query(
            url,
            headers,
            entity_row_query(template_query, entity, row_code),
            retries=retries,
            timeout=timeout,
        )
        frame = parse_any_response(response)
        return entity, row_code, frame, has_restart_token(response), None
    except Exception as exc:
        return entity, row_code, pd.DataFrame(), False, str(exc)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"templates": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load manifest {path}: {exc}") from exc


def load_discovery_cache(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load discovery cache {path}: {exc}") from exc
    values = payload.get("values")
    return values if isinstance(values, list) else None


def save_discovery_cache(
    path: Path, values: list[str], date_str: str, kind: str
) -> None:
    payload = {
        "date": date_str,
        "kind": kind,
        "count": len(values),
        "updated_at": datetime.now().isoformat(),
        "values": values,
    }
    save_manifest(path, payload)


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def download_template(
    token: TokenManager,
    template: str,
    entities: list[str],
    output_dir: Path,
    workers: int,
    timeout: int,
    partition_timeout: int,
    partition_retries: int,
    request_delay_ms: int,
    rate_limiter: RateLimiter | None,
    partition_chunk_size: int,
    skip_template_query: bool = False,
) -> dict[str, Any]:
    code = template_code(template)
    if code in BROKEN_TEMPLATES:
        return {"status": "skipped", "rows": 0, "reason": "known broken"}

    token.ensure_fresh()
    query = modify_query(token.base_query, template, max_rows=5000)
    template_restart_token = False
    template_rows = 0
    if skip_template_query:
        template_restart_token = True
        log.info(
            "  %s skipping template-level query based on date-specific manifest", code
        )
    try:
        if skip_template_query:
            raise RuntimeError("planned partitioning")
        polite_delay(request_delay_ms, rate_limiter)
        response = execute_query(
            token.url, token.headers, query, retries=3, timeout=timeout
        )
        token.mark_request()
        frame = parse_any_response(response)
        template_rows = len(frame)
        template_restart_token = has_restart_token(response)
        if not frame.empty and not template_restart_token:
            out = output_dir / template_filename(template)
            tmp = out.with_suffix(out.suffix + ".tmp")
            frame.to_csv(tmp, index=False, encoding="utf-8-sig")
            tmp.replace(out)
            return {
                "status": "complete",
                "rows": len(frame),
                "partitioned": False,
                "template_rows": template_rows,
                "template_restart_token": template_restart_token,
                "entity_restart_token_count": 0,
                "row_partition_restart_token_count": 0,
            }
        log.warning(
            "  %s template response truncated/empty: rows=%d RT=%s",
            code,
            len(frame),
            template_restart_token,
        )
    except Exception as exc:
        log.warning("  %s template query failed, trying partitions: %s", code, exc)

    frames: list[pd.DataFrame] = []
    failed: list[dict[str, Any]] = []
    truncated_entities: list[dict[str, Any]] = []
    completed_entities = 0
    for chunk_index, entity_chunk in enumerate(
        chunks(entities, partition_chunk_size), start=1
    ):
        token.ensure_fresh()
        url = token.url
        headers = dict(token.headers)
        template_query = modify_query(token.base_query, template, max_rows=5000)
        chunk_failures: list[dict[str, Any]] = []
        log.info(
            "  %s entity chunk %d: %d entities",
            code,
            chunk_index,
            len(entity_chunk),
        )
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    fetch_entity_partition,
                    url,
                    headers,
                    template_query,
                    entity,
                    partition_timeout,
                    partition_retries,
                    request_delay_ms,
                    rate_limiter,
                ): entity
                for entity in entity_chunk
            }
            for future in as_completed(futures):
                completed_entities += 1
                entity, frame, entity_rt, error = future.result()
                if error:
                    chunk_failures.append({"entity": entity, "error": error})
                elif entity_rt:
                    truncated_entities.append(
                        {
                            "entity": entity,
                            "rows": len(frame),
                            "has_restart_token": True,
                            "open_keys": extract_open_keys(frame),
                            "column_codes": extract_column_codes(frame),
                        }
                    )
                    log.warning(
                        "  %s entity has RT, retrying by row: %s rows=%d",
                        code,
                        entity,
                        len(frame),
                    )
                elif not frame.empty:
                    frames.append(frame)
                    log.info(
                        "  %s [%d/%d] %s -> %d rows",
                        code,
                        completed_entities,
                        len(entities),
                        entity,
                        len(frame),
                    )
        if chunk_failures and len(chunk_failures) / len(entity_chunk) > 0.25:
            log.warning(
                "  %s chunk %d failure rate %.1f%%; refreshing token and retrying failed entities once",
                code,
                chunk_index,
                100 * len(chunk_failures) / len(entity_chunk),
            )
            token.refresh()
            retry_query = modify_query(token.base_query, template, max_rows=5000)
            retry_failures: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        fetch_entity_partition,
                        token.url,
                        dict(token.headers),
                        retry_query,
                        item["entity"],
                        partition_timeout,
                        partition_retries,
                        request_delay_ms,
                        rate_limiter,
                    ): item["entity"]
                    for item in chunk_failures
                }
                for future in as_completed(futures):
                    entity, frame, entity_rt, error = future.result()
                    if error:
                        retry_failures.append({"entity": entity, "error": error})
                    elif entity_rt:
                        truncated_entities.append(
                            {
                                "entity": entity,
                                "rows": len(frame),
                                "has_restart_token": True,
                                "open_keys": extract_open_keys(frame),
                                "column_codes": extract_column_codes(frame),
                            }
                        )
                    elif not frame.empty:
                        frames.append(frame)
            failed.extend(retry_failures)
        else:
            failed.extend(chunk_failures)
        for item in chunk_failures:
            if item in failed:
                log.warning(
                    "  %s entity failed: %s | %s", code, item["entity"], item["error"]
                )

    row_codes = dictionary_row_codes(template)
    row_partition_rts: list[dict[str, Any]] = []
    if truncated_entities and row_codes:
        log.warning(
            "  %s retrying %d RT entities across %d dictionary rows",
            code,
            len(truncated_entities),
            len(row_codes),
        )
        row_tasks = [
            (item["entity"], row_code)
            for item in truncated_entities
            for row_code in row_codes
        ]
        row_task_chunks = chunks(row_tasks, partition_chunk_size)
        completed_row_tasks = 0
        for row_chunk_index, row_chunk in enumerate(row_task_chunks, start=1):
            log.info(
                "  %s row fallback chunk %d/%d: %d partitions (%d/%d done)",
                code,
                row_chunk_index,
                len(row_task_chunks),
                len(row_chunk),
                completed_row_tasks,
                len(row_tasks),
            )
            token.ensure_fresh()
            row_query = modify_query(token.base_query, template, max_rows=5000)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        fetch_entity_row_partition,
                        token.url,
                        dict(token.headers),
                        row_query,
                        entity,
                        row_code,
                        partition_timeout,
                        partition_retries,
                        request_delay_ms,
                        rate_limiter,
                    ): (entity, row_code)
                    for entity, row_code in row_chunk
                }
                chunk_failures: list[dict[str, Any]] = []
                for future in as_completed(futures):
                    entity, row_code, frame, row_rt, error = future.result()
                    if error:
                        chunk_failures.append(
                            {"entity": entity, "row_code": row_code, "error": error}
                        )
                    elif row_rt:
                        row_partition_rts.append(
                            {
                                "entity": entity,
                                "row_code": row_code,
                                "rows": len(frame),
                                "column_codes": extract_column_codes(frame),
                            }
                        )
                        if not frame.empty:
                            frames.append(frame)
                    elif not frame.empty:
                        frames.append(frame)
                completed_row_tasks += len(row_chunk)
                log.info(
                    "  %s row fallback chunk %d/%d done: %d/%d partitions, failures=%d, rowRT=%d",
                    code,
                    row_chunk_index,
                    len(row_task_chunks),
                    completed_row_tasks,
                    len(row_tasks),
                    len(chunk_failures),
                    len(row_partition_rts),
                )
                if chunk_failures and len(chunk_failures) / len(row_chunk) > 0.25:
                    log.warning(
                        "  %s row chunk %d failure rate %.1f%%; refreshing token and retrying failed row partitions once",
                        code,
                        row_chunk_index,
                        100 * len(chunk_failures) / len(row_chunk),
                    )
                    token.refresh()
                    retry_query = modify_query(
                        token.base_query, template, max_rows=5000
                    )
                    with ThreadPoolExecutor(max_workers=workers) as retry_executor:
                        retry_futures = {
                            retry_executor.submit(
                                fetch_entity_row_partition,
                                token.url,
                                dict(token.headers),
                                retry_query,
                                item["entity"],
                                item["row_code"],
                                partition_timeout,
                                partition_retries,
                                request_delay_ms,
                                rate_limiter,
                            ): item
                            for item in chunk_failures
                        }
                        for future in as_completed(retry_futures):
                            entity, row_code, frame, row_rt, error = future.result()
                            if error:
                                failed.append(
                                    {
                                        "entity": entity,
                                        "row_code": row_code,
                                        "error": error,
                                    }
                                )
                            elif row_rt:
                                row_partition_rts.append(
                                    {
                                        "entity": entity,
                                        "row_code": row_code,
                                        "rows": len(frame),
                                        "column_codes": extract_column_codes(frame),
                                    }
                                )
                                if not frame.empty:
                                    frames.append(frame)
                            elif not frame.empty:
                                frames.append(frame)
                else:
                    failed.extend(chunk_failures)
        row_column_tasks = [
            (item["entity"], item["row_code"], column_code)
            for item in row_partition_rts
            for column_code in item.get("column_codes", [])
        ]
        if row_column_tasks:
            log.warning(
                "  %s retrying %d row-RT partitions across %d row-column partitions",
                code,
                len(row_partition_rts),
                len(row_column_tasks),
            )
            remaining_row_rts: list[dict[str, Any]] = []
            row_column_chunks = chunks(row_column_tasks, partition_chunk_size)
            for chunk_index, row_column_chunk in enumerate(row_column_chunks, start=1):
                log.info(
                    "  %s row-column fallback chunk %d/%d: %d partitions",
                    code,
                    chunk_index,
                    len(row_column_chunks),
                    len(row_column_chunk),
                )
                token.ensure_fresh()
                row_column_query = modify_query(
                    token.base_query, template, max_rows=5000
                )
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            fetch_entity_row_column_partition,
                            token.url,
                            dict(token.headers),
                            row_column_query,
                            entity,
                            row_code,
                            column_code,
                            partition_timeout,
                            partition_retries,
                            request_delay_ms,
                            rate_limiter,
                        ): (entity, row_code, column_code)
                        for entity, row_code, column_code in row_column_chunk
                    }
                    for future in as_completed(futures):
                        entity, row_code, column_code, frame, still_rt, error = (
                            future.result()
                        )
                        if error:
                            failed.append(
                                {
                                    "entity": entity,
                                    "row_code": row_code,
                                    "column_code": column_code,
                                    "error": error,
                                }
                            )
                        elif still_rt:
                            remaining_row_rts.append(
                                {
                                    "entity": entity,
                                    "row_code": row_code,
                                    "column_code": column_code,
                                    "rows": len(frame),
                                }
                            )
                            if not frame.empty:
                                frames.append(frame)
                        elif not frame.empty:
                            frames.append(frame)
            row_partition_rts = remaining_row_rts
    if truncated_entities and not row_codes:
        dimension_tasks = [
            (item["entity"], open_key, "open_key")
            for item in truncated_entities
            for open_key in item.get("open_keys", [])
        ]
        if not dimension_tasks:
            dimension_tasks = [
                (item["entity"], column_code, "column")
                for item in truncated_entities
                for column_code in item.get("column_codes", [])
            ]
        if dimension_tasks:
            log.warning(
                "  %s retrying %d RT entities across %d discovered dimension partitions",
                code,
                len(truncated_entities),
                len(dimension_tasks),
            )
            open_key_chunks = chunks(dimension_tasks, partition_chunk_size)
            completed_open_key_tasks = 0
            for open_key_chunk_index, open_key_chunk in enumerate(
                open_key_chunks, start=1
            ):
                log.info(
                    "  %s dimension fallback chunk %d/%d: %d partitions (%d/%d done)",
                    code,
                    open_key_chunk_index,
                    len(open_key_chunks),
                    len(open_key_chunk),
                    completed_open_key_tasks,
                    len(dimension_tasks),
                )
                token.ensure_fresh()
                open_key_query = modify_query(token.base_query, template, max_rows=5000)
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            fetch_entity_dimension_partition,
                            token.url,
                            dict(token.headers),
                            open_key_query,
                            entity,
                            open_key,
                            dimension,
                            partition_timeout,
                            partition_retries,
                            request_delay_ms,
                            rate_limiter,
                        ): (entity, open_key, dimension)
                        for entity, open_key, dimension in open_key_chunk
                    }
                    for future in as_completed(futures):
                        entity, open_key, dimension, frame, open_key_rt, error = (
                            future.result()
                        )
                        if error:
                            failed.append(
                                {
                                    "entity": entity,
                                    "dimension": dimension,
                                    "dimension_value": open_key,
                                    "error": error,
                                }
                            )
                        elif open_key_rt:
                            row_partition_rts.append(
                                {
                                    "entity": entity,
                                    "dimension": dimension,
                                    "dimension_value": open_key,
                                    "rows": len(frame),
                                }
                            )
                            if not frame.empty:
                                frames.append(frame)
                        elif not frame.empty:
                            frames.append(frame)
                completed_open_key_tasks += len(open_key_chunk)
                log.info(
                    "  %s open-key fallback chunk %d/%d done: %d/%d partitions, failures=%d, rowRT=%d",
                    code,
                    open_key_chunk_index,
                    len(open_key_chunks),
                    completed_open_key_tasks,
                    len(dimension_tasks),
                    len(failed),
                    len(row_partition_rts),
                )
        else:
            failed.extend(
                {
                    "entity": item["entity"],
                    "error": "entity partition still has RT and no fixed dictionary row codes or discovered dimension values are available",
                }
                for item in truncated_entities
            )

    token.mark_request()
    if not frames:
        return {
            "status": "failed",
            "rows": 0,
            "partitioned": True,
            "failed_entities": failed,
            "template_rows": template_rows,
            "template_restart_token": template_restart_token,
            "entity_restart_token_count": len(truncated_entities),
            "row_partition_restart_token_count": len(row_partition_rts),
        }

    out_frame = pd.concat(frames, ignore_index=True).drop_duplicates()
    out = output_dir / template_filename(template)
    tmp = out.with_suffix(out.suffix + ".tmp")
    out_frame.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(out)
    status = "partial" if failed or row_partition_rts else "complete"
    return {
        "status": status,
        "rows": len(out_frame),
        "partitioned": True,
        "failed_entities": failed,
        "template_rows": template_rows,
        "template_restart_token": template_restart_token,
        "entity_restart_token_count": len(truncated_entities),
        "row_partition_restart_token_count": len(row_partition_rts),
        "entity_restart_tokens": truncated_entities,
        "row_partition_restart_tokens": row_partition_rts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--refresh-minutes", type=int, default=12)
    parser.add_argument("--template")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--refresh-discovery",
        action="store_true",
        help="Refresh date-specific template/entity discovery caches from the portal.",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="With --resume, run only templates marked failed/partial in this date's manifest.",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--partition-timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds for entity/row partition QueryExecution calls.",
    )
    parser.add_argument(
        "--partition-retries",
        type=int,
        default=1,
        help="Retries for entity/row partition QueryExecution calls before chunk-level refresh.",
    )
    parser.add_argument(
        "--partition-chunk-size",
        type=int,
        default=100,
        help="Entity/row partition tasks per token-refreshable chunk.",
    )
    parser.add_argument(
        "--request-delay-ms",
        type=int,
        default=150,
        help="Polite per-request delay with jitter for Power BI QueryExecution calls.",
    )
    parser.add_argument(
        "--max-requests-per-minute",
        type=int,
        default=0,
        help="Process-wide QueryExecution rate cap shared across worker threads; 0 disables (default).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete this date's raw P3DH output directory and manifest before running.",
    )
    args = parser.parse_args()

    ensure_chrome_debugging()
    folder_name = date_to_folder_name(args.date)
    output_dir = OUTPUT_DIR / folder_name
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RUN_DIR / f"{folder_name}_manifest.json"
    templates_cache_path = RUN_DIR / f"{folder_name}_templates.json"
    entities_cache_path = RUN_DIR / f"{folder_name}_entities.json"
    if args.clean:
        try:
            if output_dir.exists():
                log.warning("Deleting existing output directory: %s", output_dir)
                shutil.rmtree(output_dir)
            if manifest_path.exists():
                log.warning("Deleting existing run manifest: %s", manifest_path)
                manifest_path.unlink()
            for cache_path in (templates_cache_path, entities_cache_path):
                if cache_path.exists():
                    log.warning("Deleting discovery cache: %s", cache_path)
                    cache_path.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"Failed to clean prior P3DH run artifacts: {exc}"
            ) from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)

    templates = (
        None if args.refresh_discovery else load_discovery_cache(templates_cache_path)
    )
    if templates is None:
        with sync_playwright() as p:
            templates = get_templates(p, args.date)
        save_discovery_cache(templates_cache_path, templates, args.date, "templates")
    else:
        log.info(
            "Using cached template discovery: %s (%d)",
            templates_cache_path,
            len(templates),
        )
    if args.template:
        templates = [t for t in templates if args.template in t]
    if not templates:
        raise RuntimeError("No templates matched")

    runnable_templates: list[str] = []
    for template in templates:
        code = template_code(template)
        prior = manifest["templates"].get(code, {})
        if args.resume and prior.get("status") == "complete":
            log.info("%s skipped (already complete)", code)
            continue
        if args.failed_only and prior.get("status") not in {"failed", "partial"}:
            log.info("%s skipped (not failed/partial)", code)
            continue
        runnable_templates.append(template)

    if not runnable_templates:
        log.info(
            "No runnable templates after resume/failed-only filtering; exiting before token capture."
        )
        return

    seed = runnable_templates[0]
    token = TokenManager(args.date, seed, args.refresh_minutes)
    rate_limiter = RateLimiter(args.max_requests_per_minute)
    token.refresh()

    entities = (
        None if args.refresh_discovery else load_discovery_cache(entities_cache_path)
    )
    if entities is None:
        with sync_playwright() as p:
            entities = get_entities(p, args.date)
        save_discovery_cache(entities_cache_path, entities, args.date, "entities")
    else:
        log.info(
            "Using cached entity discovery: %s (%d)", entities_cache_path, len(entities)
        )
    log.info(
        "Using %d entities and %d runnable templates",
        len(entities),
        len(runnable_templates),
    )

    for idx, template in enumerate(runnable_templates, start=1):
        code = template_code(template)
        prior = manifest["templates"].get(code, {})
        log.info("[%d/%d] %s", idx, len(runnable_templates), template[:80])
        result = download_template(
            token,
            template,
            entities,
            output_dir,
            args.workers,
            args.timeout,
            args.partition_timeout,
            args.partition_retries,
            args.request_delay_ms,
            rate_limiter,
            args.partition_chunk_size,
            skip_template_query=bool(
                args.resume and prior.get("template_restart_token")
            ),
        )
        result.update(
            {
                "template": template,
                "updated_at": datetime.now().isoformat(),
                "workers": args.workers,
                "request_delay_ms": args.request_delay_ms,
                "partition_timeout": args.partition_timeout,
                "partition_retries": args.partition_retries,
                "refresh_minutes": args.refresh_minutes,
                "max_requests_per_minute": args.max_requests_per_minute,
                "partition_chunk_size": args.partition_chunk_size,
            }
        )
        manifest["templates"][code] = result
        save_manifest(manifest_path, manifest)
        log.info("  %s %s rows=%s", code, result.get("status"), result.get("rows"))

    log.info("Done: %s", manifest_path)


if __name__ == "__main__":
    main()

"""
config/data_mappings.py — Load data mappings from YAML.

Provides access to:
- Projection model field → TREX/P3DH mappings
- Benchmarking metrics definitions
- Peer group definitions
- Validated TREX ↔ P3DH semantic equivalence mappings
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "data_mappings.yaml"

_mappings: dict | None = None


def _load() -> dict:
    global _mappings
    if _mappings is not None:
        return _mappings

    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed")
        return {}

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            _mappings = yaml.safe_load(fh) or {}
        log.debug("Loaded data_mappings.yaml")
        return _mappings
    except FileNotFoundError:
        log.warning("config/data_mappings.yaml not found")
        return {}
    except Exception as exc:
        log.error("Failed to load config/data_mappings.yaml: %s", exc)
        return {}


def get_projection_mapping(field: str, source: str = "trex") -> dict | None:
    """Get mapping for a projection model field."""
    data = _load()
    pnl = data.get("projection_model", {}).get("pnl", {})
    assets = data.get("projection_model", {}).get("assets", {})
    liabilities = data.get("projection_model", {}).get("liabilities", {})
    capital = data.get("projection_model", {}).get("capital", {})
    rwa = data.get("projection_model", {}).get("rwa", {})
    aq = data.get("projection_model", {}).get("asset_quality", {})

    all_fields = {**pnl, **assets, **liabilities, **capital, **rwa, **aq}

    if field not in all_fields:
        return None
    return all_fields[field].get(source)


def get_benchmark_metric(template: str, metric: str) -> dict | None:
    """Get P3DH benchmarking metric definition."""
    data = _load()
    bench = data.get("benchmarking", {})

    for section in bench.values():
        if isinstance(section, dict) and section.get("template") == template:
            items = section.get("items", {})
            return items.get(metric)

    return None


def list_benchmark_metrics() -> list[tuple[str, str, str]]:
    """List all benchmarking metrics as (template, metric, description)."""
    data = _load()
    bench = data.get("benchmarking", {})
    results = []

    for section_name, section in bench.items():
        if isinstance(section, dict):
            template = section.get("template", "")
            items = section.get("items", {})
            for metric_name, metric_def in items.items():
                desc = metric_def.get("description", "")
                results.append((template, metric_name, desc))

    return results


def get_peer_groups() -> dict:
    """Get peer group definitions."""
    data = _load()
    return data.get("peer_groups", {})


# -----------------------------------------------------------------------------
# Validated TREX <-> P3DH Mappings
# -----------------------------------------------------------------------------

def get_validated_mappings() -> dict:
    """
    Get all validated TREX <-> P3DH semantic equivalence mappings.
    
    Returns dict: {(trex_template, trex_item): (p3dh_template, p3dh_row, matching_banks, avg_diff_pct)}
    """
    try:
        from config.validated_mappings import VALIDATED_MAPPINGS
        return VALIDATED_MAPPINGS
    except ImportError:
        log.warning("Validated mappings not found")
        return {}


def trex_to_p3dh(trex_template: str, trex_item: int) -> tuple | None:
    """
    Look up P3DH equivalent for a TREX template/item.
    
    Args:
        trex_template: e.g., "Capital", "RWA OV1", "NPE"
        trex_item: SDD item code, e.g., 2520102
    
    Returns:
        (p3dh_template_prefix, p3dh_row, matching_banks, avg_diff_pct) or None
    """
    mappings = get_validated_mappings()
    return mappings.get((trex_template, trex_item))


def p3dh_to_trex(p3dh_template_prefix: str, p3dh_row: int) -> list[tuple]:
    """
    Look up TREX equivalents for a P3DH template/row.
    
    Args:
        p3dh_template_prefix: e.g., "K_61.00", "K_66.01"
        p3dh_row: row number, e.g., 10, 370
    
    Returns:
        List of (trex_template, trex_item, matching_banks, avg_diff_pct)
    """
    mappings = get_validated_mappings()
    results = []
    p3dh_row_str = str(p3dh_row).zfill(4)  # Pad to 4 digits
    
    for (t_template, t_item), (p_template, p_row, banks, diff) in mappings.items():
        # Check both with and without leading zeros
        p_row_str = str(p_row).zfill(4) if isinstance(p_row, (int, float)) else str(p_row)
        
        if p_template.startswith(p3dh_template_prefix):
            # Handle different row formats (370, 0370, etc.)
            row_matches = (
                int(p_row_str) == p3dh_row or
                int(p_row_str.replace('0', '', 1)) == p3dh_row or  # Remove leading zero
                str(int(p_row)) == str(p3dh_row)
            )
            if row_matches:
                results.append((t_template, t_item, banks, diff))
    
    return results


def list_validated_trex_items() -> list[tuple[str, int]]:
    """List all TREX template/item pairs with validated P3DH mappings."""
    mappings = get_validated_mappings()
    return list(mappings.keys())


def get_mapping_summary() -> dict:
    """Get summary of validated mappings by TREX template."""
    mappings = get_validated_mappings()
    summary = {}
    for (t_template, t_item), (p_template, p_row, banks, diff) in mappings.items():
        if t_template not in summary:
            summary[t_template] = {"count": 0, "p3dh_templates": set()}
        summary[t_template]["count"] += 1
        summary[t_template]["p3dh_templates"].add(p_template[:20])
    
    # Convert sets to lists for JSON serialization
    for k in summary:
        summary[k]["p3dh_templates"] = list(summary[k]["p3dh_templates"])
    
    return summary


if __name__ == "__main__":
    import json

    data = _load()
    print(json.dumps(data, indent=2, default=str))
    
    print("\n\n=== Validated Mappings Summary ===")
    summary = get_mapping_summary()
    print(json.dumps(summary, indent=2))

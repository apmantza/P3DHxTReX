"""
config/loader.py — Load plan defaults from config/plan_defaults.yaml.

Returns two flat dicts matching the engine's _DEFAULT_RATE_ENV /
_DEFAULT_PORTFOLIO conventions so the merge logic in run_projection()
is unchanged.

Merge order (lowest → highest priority):
    hardcoded fallback inside this module
        ← config/plan_defaults.yaml
            ← config/current_rates.json (rate values)
                ← plan.rate_environment / plan.portfolio_allocations  (DB)
                    ← scenario.macro_assumptions  (DB)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "plan_defaults.yaml"
_RATES_JSON_PATH = Path(__file__).parent / "current_rates.json"

# Which top-level YAML sections map to the rate dict vs the portfolio dict.
_RATE_SECTIONS = {"rate_environment"}
_PORTFOLIO_SECTIONS = {
    "portfolio", "yields", "fees", "opex", "other_income",
    "tax", "credit", "deposit", "funding", "capital",
    "payout", "oci", "liquidity", "benchmarking", "ecl", "raroc",
    "repricing", "funding_betas", "liquidity_rates", "capital_regulatory",
}

_DATA_MAPPINGS_PATH = Path(__file__).parent / "data_mappings.yaml"


def _flatten(section: dict) -> dict:
    """Flatten one YAML section dict (one level deep)."""
    out: dict = {}
    for k, v in section.items():
        out[k] = v
    return out


def _load_rates_from_json() -> dict:
    """Load current rates from current_rates.json."""
    rates = {}
    try:
        if _RATES_JSON_PATH.exists():
            with open(_RATES_JSON_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            assumptions = data.get("assumptions_2025_q1", {})
            for rate_name, value in assumptions.items():
                key = rate_name.lower().replace("euribor_", "euribor_")
                if rate_name == "DFR":
                    rates["policy_rate"] = value
                elif rate_name == "EURIBOR_3M":
                    rates["euribor_3m"] = value
                elif rate_name == "EURIBOR_6M":
                    rates["euribor_6m"] = value
                else:
                    rates[key] = value
            log.debug("Loaded %d rate values from current_rates.json", len(rates))
    except Exception as exc:
        log.warning("Could not load current_rates.json: %s", exc)
    return rates


def load_defaults() -> tuple[dict, dict]:
    """
    Load config/plan_defaults.yaml and return (rate_defaults, portfolio_defaults).

    Falls back to empty dicts (engine hardcoded values take over) if the file
    is missing or cannot be parsed.
    """
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed — using engine hardcoded defaults. "
                    "Install with: pip install pyyaml")
        return {}, {}

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        log.warning("config/plan_defaults.yaml not found — using engine hardcoded defaults")
        return {}, {}
    except Exception as exc:
        log.error("Failed to load config/plan_defaults.yaml: %s — using hardcoded defaults", exc)
        return {}, {}

    rate_defaults: dict = {}
    portfolio_defaults: dict = {}

    for section_name, section_data in cfg.items():
        if not isinstance(section_data, dict):
            continue
        flat = _flatten(section_data)
        if section_name in _RATE_SECTIONS:
            rate_defaults.update(flat)
        elif section_name in _PORTFOLIO_SECTIONS:
            portfolio_defaults.update(flat)
        else:
            log.debug("Unknown config section '%s' — ignored", section_name)

    json_rates = _load_rates_from_json()
    rate_defaults.update(json_rates)

    log.debug(
        "Loaded plan_defaults.yaml: %d rate keys, %d portfolio keys",
        len(rate_defaults), len(portfolio_defaults),
    )
    return rate_defaults, portfolio_defaults


def load_ecl_defaults() -> dict:
    """Load ECL defaults from plan_defaults.yaml."""
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed")
        return {}

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.warning("Could not load ECL defaults: %s", exc)
        return {}

    ecl_section = cfg.get("ecl", {})
    log.debug("Loaded ECL defaults: %d keys", len(ecl_section))
    return ecl_section


def load_raroc_defaults() -> dict:
    """Load RAROC defaults from plan_defaults.yaml."""
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed")
        return {}

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.warning("Could not load RAROC defaults: %s", exc)
        return {}

    raroc_section = cfg.get("raroc", {})
    log.debug("Loaded RAROC defaults: %d keys", len(raroc_section))
    return raroc_section


def load_sdd_codes() -> dict:
    """Load SDD item codes from data_mappings.yaml."""
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed")
        return {}

    try:
        with open(_DATA_MAPPINGS_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.warning("Could not load SDD codes: %s", exc)
        return {}

    sdd_section = cfg.get("sdd_codes", {})
    log.debug("Loaded SDD codes: %d categories", len(sdd_section))
    return sdd_section


def load_config(section: str) -> dict:
    """Load a named config section from plan_defaults.yaml."""
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed")
        return {}

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.warning(f"Could not load config section '{section}': %s", exc)
        return {}

    section_data = cfg.get(section, {})
    log.debug("Loaded config '%s': %d keys", section, len(section_data))
    return section_data

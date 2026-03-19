"""
Populate the `banks` table from:
  1. data/processed/trex_institutions.csv  — 120 TrEx 2025 banks (LEI + name + country)
  2. data/processed/p3dh_normalized.csv    — 40 P3DH banks (name + country, no LEI)

After loading banks, also patches peer_data.bank_name from the LEI→name map so
human-readable names are stored alongside the LEI identifier.

NBG (LEI: 5UMCZOEYKCVFAW8ZLO05) is automatically included as the subject bank.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from db.engine import get_engine
from db.models import Base, Bank

DB_PATH = repo_root / "data" / "processed" / "bbirr.db"
TREX_INST = repo_root / "data" / "processed" / "trex_institutions.csv"
P3DH_NORM = repo_root / "data" / "processed" / "p3dh_normalized.csv"

# Country name → ISO-2 mapping for P3DH country strings
COUNTRY_NAME_TO_ISO2 = {
    "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR",
    "Cyprus": "CY", "Czech Republic": "CZ", "Denmark": "DK", "Estonia": "EE",
    "Finland": "FI", "France": "FR", "Germany": "DE", "Greece": "GR",
    "Hungary": "HU", "Ireland": "IE", "Italy": "IT", "Latvia": "LV",
    "Lithuania": "LT", "Luxembourg": "LU", "Malta": "MT", "Netherlands": "NL",
    "Poland": "PL", "Portugal": "PT", "Romania": "RO", "Slovakia": "SK",
    "Slovenia": "SI", "Spain": "ES", "Sweden": "SE",
}


def load_trex_banks(engine) -> dict[str, int]:
    """Insert all TrEx institutions. Returns lei→bank_id map."""
    df = pd.read_csv(TREX_INST, encoding="utf-8", dtype=str)
    df = df[["Country", "LEI_Code", "Name"]].dropna(subset=["LEI_Code", "Name"])
    df["Country"] = df["Country"].str.strip().str.upper()
    df["LEI_Code"] = df["LEI_Code"].str.strip()

    Session = sessionmaker(bind=engine)
    lei_to_id: dict[str, int] = {}

    with Session() as session:
        for _, row in df.iterrows():
            lei = row["LEI_Code"]
            existing = session.query(Bank).filter_by(lei=lei).first()
            if existing:
                lei_to_id[lei] = existing.id
                continue
            bank = Bank(
                name=row["Name"].strip(),
                lei=lei,
                country=row["Country"],
                approach="UNKNOWN",
                tier="Large",               # TrEx banks are all significant institutions
                systemic_importance="OTHER",
            )
            session.add(bank)
            session.flush()
            lei_to_id[lei] = bank.id
        session.commit()

    print(f"  TrEx banks loaded: {len(lei_to_id)}")
    return lei_to_id


def _prompt_for_bank_details(name: str, country_iso2: str) -> dict | None:
    """
    Interactive prompt when a P3DH bank cannot be auto-resolved from the
    institutions list. Returns a dict of Bank fields or None to skip.
    Called only in interactive mode (stdin is a tty).
    """
    import sys
    print(f"\n  *** Unresolved bank: '{name}' ({country_iso2}) ***")
    print("  This bank is not in the TrEx institutions list.")
    print("  Enter details below (press Enter to leave optional fields blank).")
    print("  Type 'skip' at the LEI prompt to defer this bank.")

    lei = input("  LEI (20-char): ").strip() or None
    if lei and lei.lower() == "skip":
        print(f"  Skipping '{name}' — will be stored without LEI.")
        lei = None
    approach = input("  Approach [SA/IRB/UNKNOWN] (default UNKNOWN): ").strip().upper() or "UNKNOWN"
    tier = input("  Tier [Large/Other] (default Large): ").strip() or "Large"
    systemic = input("  Systemic importance [GSIB/DSIB/OTHER] (default OTHER): ").strip().upper() or "OTHER"
    peer_group = input("  Peer group (optional): ").strip() or None

    return {
        "lei": lei,
        "approach": approach,
        "tier": tier,
        "systemic_importance": systemic,
        "peer_group": peer_group,
    }


def load_p3dh_banks(engine, lei_to_id: dict[str, int], interactive: bool = True) -> dict[str, int]:
    """
    Insert P3DH banks not already in the DB (matched by name).
    For banks not in the institutions list, prompts the user for LEI and
    other fields when running interactively, or stores with a warning in
    batch mode.
    Returns name→bank_id map for all P3DH banks.
    """
    import sys

    # Read unique (entity_name, country) from P3DH
    df = pd.read_csv(P3DH_NORM, encoding="utf-8", usecols=["entity_name", "country"])
    p3dh_banks = df.drop_duplicates().dropna(subset=["entity_name"])

    Session = sessionmaker(bind=engine)
    name_to_id: dict[str, int] = {}
    new_count = 0

    with Session() as session:
        # Build name→id map from existing banks (by name and by LEI)
        existing_by_name = {b.name: b.id for b in session.query(Bank).all()}

        for _, row in p3dh_banks.iterrows():
            name = str(row["entity_name"]).strip()
            country_name = str(row["country"]).strip() if pd.notna(row["country"]) else ""
            iso2 = COUNTRY_NAME_TO_ISO2.get(country_name, country_name[:2].upper())

            if name in existing_by_name:
                name_to_id[name] = existing_by_name[name]
                continue

            # Not matched — need additional data
            extra: dict = {}
            is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
            if interactive and is_tty:
                extra = _prompt_for_bank_details(name, iso2) or {}
            else:
                print(f"  WARNING: unresolved P3DH bank '{name}' ({iso2}) — no LEI. "
                      "Run interactively to provide details.")

            bank = Bank(
                name=name,
                lei=extra.get("lei"),
                country=iso2,
                approach=extra.get("approach", "UNKNOWN"),
                tier=extra.get("tier", "Large"),
                systemic_importance=extra.get("systemic_importance", "OTHER"),
                peer_group=extra.get("peer_group"),
            )
            session.add(bank)
            session.flush()
            existing_by_name[name] = bank.id
            name_to_id[name] = bank.id
            new_count += 1

        session.commit()

    print(f"  P3DH banks: {len(name_to_id)} total, {new_count} new (not in TrEx list)")
    return name_to_id


def patch_peer_data_names(engine, lei_to_id: dict[str, int]) -> None:
    """
    Update peer_data.bank_name from LEI to human-readable name where available.
    peer_data currently stores the LEI in both bank_name and bank_lei columns.
    """
    Session = sessionmaker(bind=engine)
    with Session() as session:
        banks = {b.lei: b.name for b in session.query(Bank).filter(Bank.lei.isnot(None))}

    if not banks:
        return

    with engine.begin() as conn:
        for lei, name in banks.items():
            conn.execute(
                text("UPDATE peer_data SET bank_name = :name WHERE bank_lei = :lei AND bank_name = :lei"),
                {"name": name, "lei": lei},
            )

    print(f"  Patched peer_data.bank_name for {len(banks)} LEIs")


def main() -> None:
    engine = get_engine(DB_PATH)
    Base.metadata.create_all(engine)

    print("Loading TrEx institutions...")
    lei_to_id = load_trex_banks(engine)

    print("Loading P3DH banks...")
    name_to_id = load_p3dh_banks(engine, lei_to_id)

    print("Patching peer_data bank names...")
    patch_peer_data_names(engine, lei_to_id)

    # Summary
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM banks")).scalar()
    print(f"\nDone — {n} banks in DB")

    # Confirm NBG
    with engine.connect() as conn:
        nbg = conn.execute(
            text("SELECT id, name, country, lei FROM banks WHERE lei = '5UMCZOEYKCVFAW8ZLO05'")
        ).fetchone()
    if nbg:
        print(f"Subject bank: [{nbg[0]}] {nbg[1]} ({nbg[2]}) — LEI {nbg[3]}")
    else:
        print("WARNING: NBG not found in banks table")


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from modules.ingestion.p3dh import summarize_p3dh, summarize_p3dh_directory
from modules.ingestion.p3dh_normalize import (
    append_incremental,
    export_skipped_keys,
    normalize_all_p3dh,
    normalize_p3dh_export,
    split_incremental,
    upsert_p3dh_sqlite,
)
from modules.ingestion.canonical import build_canonical, build_divergence_report
from modules.ingestion.canonical_enrich import build_canonical_enriched
from modules.ingestion.peerdata import build_peerdata
from modules.ingestion.trex_metadata import export_all_sheets, export_institutions
from modules.ingestion.trex import (
    summarize_trex,
    summarize_trex_sdd_coverage,
    extract_trex_unmatched,
    enrich_trex_with_sdd,
)


def main() -> None:
    trex_dir = repo_root / "data" / "raw" / "TrEx2025"
    sdd_path = trex_dir / "SDD.xlsx"
    trex_metadata_path = trex_dir / "TR_Metadata.xlsx"
    p3dh_dir = repo_root / "data" / "raw" / "P3DH"
    processed_dir = repo_root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    trex_summary = summarize_trex(trex_dir)
    trex_coverage = summarize_trex_sdd_coverage(trex_dir, sdd_path)
    p3dh_summary = summarize_p3dh_directory(p3dh_dir)

    print("TREX summary")
    for item in trex_summary:
        print(f"- {item.name}: {item.rows} rows, {item.columns} cols")

    print("\nTREX SDD coverage")
    for name, stats in trex_coverage.items():
        rate = stats["match_rate"] * 100
        print(f"- {name}: {stats['matched_rows']}/{stats['total_rows']} ({rate:.1f}%)")

    unmatched = extract_trex_unmatched(trex_dir, sdd_path)
    unmatched_path = processed_dir / "trex_unmatched.csv"
    if not unmatched.empty:
        unmatched.to_csv(unmatched_path, index=False, encoding="utf-8-sig")
        print(f"\nTREX unmatched exported to {unmatched_path}")
    else:
        print("\nTREX unmatched: none")

    trex_enriched_path = processed_dir / "trex_enriched.csv"
    trex_enriched = enrich_trex_with_sdd(trex_dir, sdd_path)
    trex_concat = pd.concat(trex_enriched.values(), ignore_index=True)
    trex_concat.to_csv(trex_enriched_path, index=False, encoding="utf-8-sig")
    print(f"TREX enriched exported to {trex_enriched_path}")

    institutions_path = processed_dir / "trex_institutions.csv"
    export_institutions(trex_metadata_path, institutions_path)
    print(f"TREX institutions exported to {institutions_path}")

    metadata_dir = processed_dir / "trex_metadata"
    exported = export_all_sheets(trex_metadata_path, metadata_dir)
    print(f"TREX metadata sheets exported to {metadata_dir} ({len(exported)} files)")

    print("\nP3DH summary")
    for item in p3dh_summary:
        print(f"- {item.path.name}#{item.name}: {item.rows} rows, {item.columns} cols")

    normalized = normalize_all_p3dh(p3dh_dir)
    normalized_path = processed_dir / "p3dh_normalized.csv"
    skipped_keys_path = processed_dir / "p3dh_skipped_keys.csv"
    to_append, skipped_frame, existing = split_incremental(normalized, normalized_path)
    combined, inserted, skipped = append_incremental(normalized, normalized_path)
    combined.to_csv(normalized_path, index=False, encoding="utf-8-sig")
    print(f"\nP3DH normalized exported to {normalized_path}")
    print(f"P3DH incremental: inserted {inserted}, skipped {skipped}")

    skipped_exported = export_skipped_keys(normalized, normalized_path, skipped_keys_path)
    if skipped_exported:
        print(f"P3DH skipped keys exported to {skipped_keys_path}")

    if not to_append.empty:
        delta = to_append.copy()
        delta["reference_date"] = delta["reference_date"].dt.strftime("%Y-%m-%d")
        report = (
            delta.groupby(["reference_date", "template"], dropna=False)
            .agg(rows=("fact_value", "size"), banks=("entity_name", "nunique"))
            .reset_index()
            .sort_values(["reference_date", "template"])
        )
        delta_path = processed_dir / "p3dh_delta_by_date_template.csv"
        report.to_csv(delta_path, index=False, encoding="utf-8-sig")
        print(f"P3DH delta report exported to {delta_path}")

    sqlite_path = processed_dir / "p3dh.sqlite"
    db_inserted, db_skipped = upsert_p3dh_sqlite(normalized, sqlite_path)
    print(f"P3DH sqlite upsert: inserted {db_inserted}, skipped {db_skipped}")

    trex_enriched_path = processed_dir / "trex_enriched.csv"
    if trex_enriched_path.exists():
        canonical = build_canonical(normalized_path, trex_enriched_path)
        canonical_path = processed_dir / "canonical_facts.csv"
        canonical.to_csv(canonical_path, index=False, encoding="utf-8-sig")
        print(f"Canonical facts exported to {canonical_path}")

        divergence = build_divergence_report(normalized_path, trex_enriched_path)
        divergence_path = processed_dir / "canonical_divergence.csv"
        divergence.to_csv(divergence_path, index=False, encoding="utf-8-sig")
        print(f"Divergence report exported to {divergence_path}")

        metadata_dir = processed_dir / "trex_metadata"
        canonical_enriched = build_canonical_enriched(canonical_path, trex_enriched_path, metadata_dir)
        canonical_enriched_path = processed_dir / "canonical_facts_enriched.csv"
        canonical_enriched.to_csv(canonical_enriched_path, index=False, encoding="utf-8-sig")
        print(f"Canonical facts enriched exported to {canonical_enriched_path}")

        enriched_path = processed_dir / "canonical_facts_enriched.csv"
        peerdata_source = enriched_path if enriched_path.exists() else canonical_path
        peerdata = build_peerdata(peerdata_source)
        peerdata_path = processed_dir / "peerdata.csv"
        peerdata.to_csv(peerdata_path, index=False, encoding="utf-8-sig")
        print(f"PeerData exported to {peerdata_path}")
    else:
        print("TREX enriched CSV not found; skipping canonical merge")


if __name__ == "__main__":
    main()

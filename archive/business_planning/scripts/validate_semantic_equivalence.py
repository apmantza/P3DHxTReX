"""
Validate semantic equivalence between TREX and P3DH - optimized version.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from collections import defaultdict

import pandas as pd


def validate_semantic_equivalence(
    db_path: Path,
    period: str = "2025-06-30",
    tolerance: float = 1.0,
) -> pd.DataFrame:
    """Compare TREX vs P3DH values at a given period."""
    conn = sqlite3.connect(db_path)
    
    trex = pd.read_sql(f"""
        SELECT bank_name, template, item, column, amount
        FROM peer_data
        WHERE source = 'TREX' AND period = '{period}'
    """, conn)
    
    p3dh = pd.read_sql(f"""
        SELECT bank_name, template, item, column, amount
        FROM peer_data
        WHERE source = 'P3DH' AND period = '{period}'
    """, conn)
    
    conn.close()
    
    trex["item"] = trex["item"].astype(str)
    trex["column"] = trex["column"].fillna("").astype(str)
    p3dh["item"] = p3dh["item"].astype(str)
    p3dh["column"] = p3dh["column"].fillna("").astype(str)
    
    trex_by_bank = defaultdict(dict)
    for _, r in trex.iterrows():
        key = (r["template"], r["item"], r["column"])
        trex_by_bank[r["bank_name"]][key] = r["amount"]
    
    p3dh_by_bank = defaultdict(dict)
    for _, r in p3dh.iterrows():
        key = (r["template"], r["item"], r["column"])
        p3dh_by_bank[r["bank_name"]][key] = r["amount"]
    
    common_banks = set(trex_by_bank.keys()) & set(p3dh_by_bank.keys())
    print(f"Comparing {len(common_banks)} banks at {period}")
    
    conversions = [1.0, 1_000_000, 100.0]
    
    trex_items = trex[["template", "item", "column"]].drop_duplicates().values.tolist()
    p3dh_items = p3dh[["template", "item", "column"]].drop_duplicates().values.tolist()
    
    print(f"Testing {len(trex_items)} TREX items vs {len(p3dh_items)} P3DH items...")
    
    results = []
    
    for t_template, t_item, t_col in trex_items:
        t_key = (t_template, str(t_item), str(t_col) if t_col else "")
        
        for p_template, p_item, p_col in p3dh_items:
            p_key = (str(p_template), str(p_item), str(p_col) if p_col else "")
            
            matches = []
            for bank in common_banks:
                t_val = trex_by_bank[bank].get(t_key)
                p_val = p3dh_by_bank[bank].get(p_key)
                
                if t_val and p_val and t_val != 0:
                    for conv in conversions:
                        p_converted = p_val / conv
                        diff_pct = abs(t_val - p_converted) / abs(t_val) * 100
                        if diff_pct < tolerance:
                            matches.append(diff_pct)
                            break
            
            if len(matches) >= 3:
                results.append({
                    "trex_template": t_template,
                    "trex_item": str(t_item),
                    "trex_column": str(t_col) if t_col else "",
                    "p3dh_template": p_template,
                    "p3dh_row": str(p_item),
                    "p3dh_column": str(p_col) if p_col else "",
                    "matching_banks": len(matches),
                    "avg_diff_pct": sum(matches) / len(matches),
                })
    
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("matching_banks", ascending=False)
    
    return df


def main():
    repo_root = Path(__file__).resolve().parents[1]
    db_path = repo_root / "data" / "processed" / "bbirr.db"
    
    print("=" * 60)
    print("TREX <-> P3DH Semantic Equivalence Validation")
    print("=" * 60)
    
    df = validate_semantic_equivalence(db_path, "2025-06-30")
    
    if df.empty:
        print("No matches found")
        return
    
    print(f"\nFound {len(df)} potential mappings:\n")
    
    # Group by P3DH template
    for template in df["p3dh_template"].unique()[:15]:
        subset = df[df["p3dh_template"] == template]
        print(f"{template[:50]}...")
        for _, r in subset.head(3).iterrows():
            conv_note = ""
            print(f"  TREX {r['trex_template'][:15]} item={r['trex_item']} -> P3DH row={r['p3dh_row']} : {r['matching_banks']} banks, {r['avg_diff_pct']:.2f}% diff{conv_note}")
    
    output_path = repo_root / "data" / "processed" / "semantic_validation_20250630.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()

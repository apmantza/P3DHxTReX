# P3DH & TREX Data Mapping for Projections & Benchmarking

## Status: Data Loaded

### Data Sources
- **TREX 2025**: Full annual data (~1.2M rows across 4 files)
- **P3DH**: 15 files, 101 templates, ~324K rows
- **Peer Data**: Canonical merged view in DB (~261K rows)
- **Base Year**: NBG snapshot (1,742 rows)

---

## Projection Model Requirements

### Base Year Extractor (modules/calculation/state.py)

| Template | SDD Code | Status |
|----------|----------|--------|
| P&L | 25203xx | ✓ Loaded |
| Capital | 25201xx | ✓ Loaded |
| RWA OV1 | 25202xx | ✓ Loaded |
| Assets | 25210xx | ✓ Loaded |
| Liabilities | 25212xx | ✓ Loaded |
| NPE | 25206xx | ✓ Loaded |
| Collateral | 25208xx | ✓ Loaded |
| Credit Risk IRB | 25204xx | ✓ Loaded |
| Credit Risk STA | 25205xx | ✓ Loaded |

---

## Benchmarking Metrics

### Key Metrics from P3DH (K_61.00 KM1)

| Row | Metric | Unit |
|-----|--------|------|
| 0010 | CET1 Capital | EUR |
| 0020 | Tier 1 Capital | EUR |
| 0030 | Total Capital | EUR |
| 0040 | Total RWA | EUR |
| 0050 | CET1 Ratio | % |
| 0060 | Tier 1 Ratio | % |
| 0070 | Total Capital Ratio | % |
| 0080 | Leverage Ratio | % |
| 0090 | TNS Ratio | % |

### Liquidity (K_73.00 LIQ1 - LCR)

| Row | Metric | Unit |
|-----|--------|------|
| 0100 | Total HQLA | EUR |
| 0110 | Total Outflows | EUR |
| 0120 | Total Inflows | EUR |
| 0130 | Net Cash Outflows | EUR |
| 0140 | LCR Ratio | % |

### Funding (K_74.00 LIQ2 - NSFR)

| Row | Metric | Unit |
|-----|--------|------|
| 0100 | Available Stable Funding | EUR |
| 0110 | Required Stable Funding | EUR |
| 0120 | NSFR Ratio | % |

### Credit Quality

| Template | Key Metrics |
|----------|-------------|
| K_21.01 CR1 | Performing vs Non-Performing exposures |
| K_22.01 CR2 | NPL changes ( inflow, outflow, cures, write-offs) |
| K_24.00 CR4 | Standardized RWA by exposure class |
| K_26.00 CR6 | IRB RWA by PD range |

### MREL/TLAC (K_90.01 KM2)

| Row | Metric | Unit |
|-----|--------|------|
| 0100 | MREL Capacity | EUR |
| 0110 | MREL Requirement | EUR |
| 0120 | MREL Ratio | % |

---

## What's Available for Each Bank

Query to see available data per bank:

```sql
SELECT 
    bank_name,
    COUNT(DISTINCT template) as templates,
    COUNT(*) as rows
FROM peer_data
GROUP BY bank_name
ORDER BY rows DESC
LIMIT 20;
```

---

## Data Gaps

### Missing from Current Load
- Some ESG templates (K_41-K_50) have limited bank coverage
- Not all banks report all templates

### Action Items
1. Verify base year extractor works for all required SDD codes
2. Add benchmarking percentiles (25th, 50th, 75th, 90th) for peer comparison
3. Map P3DH templates to simplified benchmarking views

---

## Files

- Raw: `data/raw/P3DH/`, `data/raw/TrEx2025/`
- Processed: `data/processed/peerdata.csv`
- DB: `data/processed/bbirr.db` (peer_data table)
- Dictionary: `data/processed/p3dh_data_dictionary.csv`

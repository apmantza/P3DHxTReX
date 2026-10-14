"""Concept of a series: its key without the frequency and the country. The same concept in two countries is the same measure, so the countries can be compared by a join on the concept."""

from __future__ import annotations


def concept_of(key: str, area: str) -> tuple[str, str]:
    """('MIR/B.A2I.AM.R.A.2240.EUR.N', 'MIR') from 'MIR.M.LU.B.A2I.AM.R.A.2240.EUR.N' and the country LU.
    A key without a country (the euro short-term rate: EST.B.EU000A2X2A25.WT) keeps all dimensions after the frequency."""
    tokens = key.split(".")
    flow, dims = tokens[0], tokens[1:]
    drop = {0}
    if area in dims[1:]:
        drop.add(dims.index(area, 1))
    return f"{flow}/" + ".".join(d for i, d in enumerate(dims) if i not in drop), flow

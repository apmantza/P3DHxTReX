"""Curve maths for the ESTR OIS curve and the expected ECB deposit rate. It has no Bloomberg code."""

from __future__ import annotations

import datetime as dt
import math

# ESTR OIS swaps: label -> (days from the start date, Bloomberg ticker without the yellow key)
OIS = {"1W": (7, "EESWE1Z"), "2W": (14, "EESWE2Z"), "3W": (21, "EESWE3Z"), "1M": (31, "EESWEA"), "2M": (61, "EESWEB"), "3M": (92, "EESWEC"),
       "6M": (183, "EESWEF"), "9M": (274, "EESWEI"), "10M": (304, "EESWEJ"), "1Y": (365, "EESWE1"), "2Y": (730, "EESWE2"), "3Y": (1095, "EESWE3"),
       "4Y": (1461, "EESWE4"), "5Y": (1826, "EESWE5"), "6Y": (2191, "EESWE6"), "7Y": (2556, "EESWE7"), "10Y": (3652, "EESWE10")}


def discount_factors(quotes: dict[str, float | None]) -> list[tuple[int, float]]:
    """Discount factors from ESTR OIS par rates (percent). Up to one year the swap pays at maturity (act/360). After one year it pays annually.

    Annual dates between two quoted tenors use log-linear interpolation of the discount factors.
    """
    nodes: list[tuple[int, float]] = [(0, 1.0)]
    for label, (days, _) in sorted(OIS.items(), key=lambda kv: kv[1][0]):
        r = quotes.get(label)
        if r is None:
            continue
        r /= 100.0
        if days <= 365:
            nodes.append((days, 1.0 / (1.0 + r * days / 360.0)))
            continue
        years = round(days / 365)
        tau = 365.0 / 360.0
        annuity = sum(df_at(nodes, 365 * k) for k in range(1, years))
        nodes.append((days, (1.0 - r * tau * annuity) / (1.0 + r * tau)))
    return nodes


def df_at(nodes: list[tuple[int, float]], day: float) -> float:
    """Discount factor at a day. The log of the factor is linear between nodes, which means a constant forward rate."""
    if day <= 0:
        return 1.0
    for (d0, f0), (d1, f1) in zip(nodes, nodes[1:]):
        if day <= d1:
            w = (day - d0) / (d1 - d0)
            return math.exp((1 - w) * math.log(f0) + w * math.log(f1))
    (d0, f0), (d1, f1) = nodes[-2], nodes[-1]
    return math.exp(math.log(f1) + (day - d1) * (math.log(f1) - math.log(f0)) / (d1 - d0))


def forward_rate(nodes: list[tuple[int, float]], a: float, b: float) -> float:
    """Average ESTR in percent (act/360) between day a and day b counted from the start date."""
    return (df_at(nodes, a) / df_at(nodes, b) - 1.0) / ((b - a) / 360.0) * 100.0


def value_on(changes: list[tuple[dt.date, float]], day: dt.date) -> float | None:
    """Value of a step series on a day. changes is sorted by date."""
    val = None
    for d, v in changes:
        if d > day:
            break
        val = v
    return val


def expected_average(as_of: dt.date, start: dt.date, end: dt.date, changes: list[tuple[dt.date, float]], nodes: list[tuple[int, float]], spread: float) -> float | None:
    """Average ECB deposit rate (percent) of the period start to end, seen from as_of.

    Days up to as_of use the realised deposit rate. Later days use the forward ESTR of the OIS curve plus the spread of the deposit rate to ESTR at as_of.
    """
    total, n = 0.0, 0
    if start <= as_of:
        stop = min(end, as_of)
        base = value_on(changes, start)
        points = ([(start, base)] if base is not None else []) + [(d, v) for d, v in changes if start < d <= stop]
        for k, (d, v) in enumerate(points):
            nxt = points[k + 1][0] if k + 1 < len(points) else stop + dt.timedelta(days=1)
            days = (nxt - d).days
            total += v * days
            n += days
    first_future = max(start, as_of + dt.timedelta(days=1))
    if end >= first_future:
        days = (end - first_future).days + 1
        a = (first_future - as_of).days - 1
        total += (forward_rate(nodes, a, a + days) + spread) * days
        n += days
    return total / n if n else None


def expected_year_average(as_of: dt.date, year: int, changes, nodes, spread: float) -> float | None:
    return expected_average(as_of, dt.date(year, 1, 1), dt.date(year, 12, 31), changes, nodes, spread)

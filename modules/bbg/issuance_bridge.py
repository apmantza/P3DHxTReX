"""Sheet Bridge of the issuance workbook: issued debt (P3DH CC2) and MREL-eligible debt (P3DH TLAC1) for each issuer, the own funds and eligible liabilities that follow,
and a check against the reported KM2 ratios. Green cells are P3DH data. Black cells are formulas. Bloomberg is a cross-check at the foot. Labels follow ASD-STE100."""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .issuance import CC2_GROUPS, STRUCTURED

HEAD, HEAD_FONT = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
GREEN, BOLD = Font(color="006100"), Font(bold=True)


def _d(v: Any) -> dt.date | None:
    return None if not v else dt.date.fromisoformat(str(v)[:10])


def write_bridge(ws, issues_col: Callable[[str], str], n_issues: int, banks_meta: list[tuple[str, str]], bridge: dict[str, dict[str, Any]], issues) -> None:
    """issues_col(key) gives the column letter of a field in the sheet Issues. issues: the frame of the sheet Issues (for the flag on the largest note)."""
    banks = [s for s, _ in banks_meta if bridge.get(s)]
    ws["A1"] = "Issued debt and MREL-eligible debt from P3DH, with a check against the reported MREL ratios. EUR million."
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Green: P3DH data (CC2 liabilities, TLAC1, KM2). Black: formula. The date of each bank is the newest date that has both CC2 liability lines and TLAC1."
    if not banks:
        ws["A4"] = "No bank has CC2 liability lines and TLAC1 in P3DH."
        return
    cols = {s: get_column_letter(2 + i) for i, s in enumerate(banks)}
    note_col = 2 + len(banks)
    rows: dict[str, int] = {}
    state = {"r": 4}

    def section(text: str) -> None:
        r = state["r"]
        for j, v in enumerate([text] + banks + ["Source and note"], start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font, c.fill = HEAD_FONT, HEAD
            c.alignment = Alignment(horizontal="left" if j in (1, note_col) else "center")
        state["r"] += 1

    def line(key: str, label: str, values, fmt: str = "#,##0.0", note: str = "", bold: bool = False, data: bool = False) -> None:
        """values: a dict {bank: value}, or a function f(bank, column letter) that returns a formula (or None)."""
        r = state["r"]
        ws.cell(row=r, column=1, value=label).font = BOLD if bold else Font()
        for s in banks:
            v = values(s, cols[s]) if callable(values) else values.get(s)
            if v is None:
                continue
            c = ws[f"{cols[s]}{r}"]
            c.value, c.number_format = v, fmt
            c.font = GREEN if data else (BOLD if bold else Font())
        if note:
            ws.cell(row=r, column=note_col, value=note)
        rows[key] = r
        state["r"] += 1

    R = lambda k, c: f"{c}{rows[k]}"  # noqa: E731
    t = lambda k: {s: bridge[s]["tlac"].get(k) for s in banks}  # noqa: E731
    km = lambda k: {s: bridge[s]["km2"].get(k) for s in banks}  # noqa: E731  (KM2 of the TLAC1 date)
    kn = lambda k: {s: bridge[s]["km2_new"].get(k) for s in banks}  # noqa: E731  (newest KM2)

    section("Reference dates")
    line("d_tlac", "Date of CC2 and TLAC1", {s: _d(bridge[s]["date"]) for s in banks}, "yyyy-mm-dd", "Newest date with both templates.", data=True)
    line("d_km2", "Date of the newest KM2", {s: _d(bridge[s]["km2_new"].get("date")) for s in banks}, "yyyy-mm-dd", "KM2 can be newer than TLAC1: some banks file TLAC1 in the annual Pillar 3 only. Section D uses it.", data=True)
    state["r"] += 1

    section("A. Issued debt (CC2 liabilities)")
    for key, label in CC2_GROUPS:
        labels = "; ".join(f"{s}: {', '.join(bridge[s]['cc2_labels'][key])}" for s in banks if key in bridge[s]["cc2_labels"])
        line("cc2_" + key, label, {s: bridge[s]["cc2"].get(key) for s in banks}, note="CC2 lines used: " + labels if labels else "", data=True)
    line("at1_add", "AT1 from TLAC1 when CC2 has no AT1 line", {s: (0.0 if bridge[s]["cc2"].get("at1") else (bridge[s]["tlac"].get("at1") or 0.0)) for s in banks},
         note="A bank can report its AT1 in equity, outside the liability lines of CC2.", data=True)
    line("issued", "Total issued debt", lambda s, c: f"=SUM({R('cc2_debt', c)}:{R('cc2_at1', c)})+{R('at1_add', c)}", bold=True, note="Debt securities, fair-value liabilities, subordinated debts, and AT1.")
    state["r"] += 1

    section("B. MREL-eligible debt (TLAC1)")
    line("at1", "AT1 (row 2)", t("at1"), data=True)
    line("t2", "Tier 2 in own funds (row 6)", t("t2"), data=True)
    line("t2am", "Tier 2 with 1 to 5 years left, counted as a liability (row EU-12c)", t("t2_am"), data=True)
    line("snp", "Senior non-preferred (rows 12 and EU-12b)", {s: (bridge[s]["tlac"].get("snp") or 0.0) + (bridge[s]["tlac"].get("snp_b") or 0.0) for s in banks}, data=True)
    line("nonsub", "Non-subordinated eligible liabilities (row 14, else rows 13 and EU-13a)",
         {s: (bridge[s]["tlac"]["ns14"] if bridge[s]["tlac"].get("ns14") is not None else (bridge[s]["tlac"].get("ns13") or 0.0) + (bridge[s]["tlac"].get("ns13a") or 0.0)) for s in banks}, data=True)
    line("elig", "Eligible debt, gross", lambda s, c: f"=SUM({R('at1', c)}:{R('nonsub', c)})", bold=True)
    line("not", "Not eligible (issued less eligible)", lambda s, c: f"={R('issued', c)}-{R('elig', c)}",
         note="The accounting lines and the TLAC1 types do not map one to one: the Tier 2 of one bank sits in its subordinated line, the Tier 2 of another in its debt securities.")
    line("share", "Eligible share of issued debt", lambda s, c: f"=IF({R('issued', c)}>0,{R('elig', c)}/{R('issued', c)},0)", "0.0%")
    line("ded", "Deduction of own holdings of other eligible instruments (row 20)", {s: bridge[s]["tlac"].get("ded") or 0.0 for s in banks}, data=True, note="Negative. An empty row counts as 0.")
    line("net", "Eligible debt after deduction", lambda s, c: f"={R('elig', c)}+{R('ded', c)}", bold=True)
    line("share_net", "Eligible share of issued debt after deduction", lambda s, c: f"=IF({R('issued', c)}>0,{R('net', c)}/{R('issued', c)},0)", "0.0%")
    state["r"] += 1

    section("C. Own funds and eligible liabilities, and the check against KM2")
    line("cet1", "CET1 (row 1)", t("cet1"), data=True)
    line("total", "Own funds and eligible liabilities, computed", lambda s, c: f"={R('net', c)}+{R('cet1', c)}", bold=True)
    line("rep_total", "Reported (KM2 row 1)", km("total"), data=True, note="KM2 of the same date as TLAC1.")
    line("diff", "Difference (EUR m)", lambda s, c: f'=IF(ISNUMBER({R("rep_total", c)}),{R("total", c)}-{R("rep_total", c)},"n/a")', "0.0")
    line("trea", "Total risk exposure amount (TREA)", t("trea"), data=True, note="TLAC1 row 23.")
    line("ratio", "Own funds and eligible liabilities, % of TREA, computed", lambda s, c: f"=IF({R('trea', c)}>0,{R('total', c)}/{R('trea', c)},0)", "0.00%", bold=True)
    line("rep_ratio", "Reported (KM2 row 3)", km("ratio"), "0.00%", data=True, note="The bank rounds it to 0.01 percentage point.")
    line("bp", "Difference (bp)", lambda s, c: f'=IF(ISNUMBER({R("rep_ratio", c)}),({R("ratio", c)}-{R("rep_ratio", c)})*10000,"n/a")', "0.00", note="Within 0.5 bp is a match: that is the rounding of the reported ratio.")
    line("sub", "Own funds and subordinated liabilities, computed", lambda s, c: f"={R('cet1', c)}+{R('at1', c)}+{R('t2', c)}+{R('t2am', c)}+{R('snp', c)}", note="CET1, AT1, Tier 2 including the amortised part, and senior non-preferred.")
    line("sub_ratio", "Subordinated, % of TREA, computed", lambda s, c: f"=IF({R('trea', c)}>0,{R('sub', c)}/{R('trea', c)},0)", "0.00%")
    line("rep_sub", "Reported (KM2 row 3a)", km("sub_ratio"), "0.00%", data=True)
    line("bp_sub", "Difference (bp)", lambda s, c: f'=IF(ISNUMBER({R("rep_sub", c)}),({R("sub_ratio", c)}-{R("rep_sub", c)})*10000,"n/a")', "0.00")
    state["r"] += 1

    section("D. Newest KM2 (totals only, no line items)")
    line("k_tot", "Own funds and eligible liabilities", kn("total"), data=True)
    line("k_sub", "of which own funds and subordinated liabilities", kn("sub"), data=True)
    line("k_non", "Non-subordinated eligible liabilities, after deduction", lambda s, c: f'=IF(AND(ISNUMBER({R("k_tot", c)}),ISNUMBER({R("k_sub", c)})),{R("k_tot", c)}-{R("k_sub", c)},"n/a")')
    line("k_trea", "TREA", kn("trea"), data=True)
    line("k_ratio", "% of TREA, computed", lambda s, c: f'=IF(AND(ISNUMBER({R("k_tot", c)}),ISNUMBER({R("k_trea", c)})),{R("k_tot", c)}/{R("k_trea", c)},"n/a")', "0.00%")
    line("k_rep", "Reported", kn("ratio"), "0.00%", data=True)
    line("k_sub_ratio", "Subordinated, % of TREA, computed", lambda s, c: f'=IF(AND(ISNUMBER({R("k_sub", c)}),ISNUMBER({R("k_trea", c)})),{R("k_sub", c)}/{R("k_trea", c)},"n/a")', "0.00%")
    line("k_sub_rep", "Reported", kn("sub_ratio"), "0.00%", data=True)
    state["r"] += 1

    section("E. Cross-check with Bloomberg (nominal amounts of notes)")
    rng = lambda k: f"Issues!${issues_col(k)}$2:${issues_col(k)}${n_issues}"  # noqa: E731
    line("bbg", "Notes issued by the date above that are still outstanding today", lambda s, c: f'=SUMIFS({rng("eur")},{rng("issuer")},"{s}",{rng("active")},"Y",{rng("issue_date")},"<="&{R("d_tlac", c)})',
         note="A nominal amount, not a carrying amount. Two causes of a difference: a note that matured or was called after the date is missing here, and a note that the bank holds or pledges itself (for example a retained covered bond) can be in Bloomberg and not in the accounts.")
    line("bbg_diff", "Difference to total issued debt", lambda s, c: f"={R('bbg', c)}-{R('issued', c)}")
    big = {}
    notes = {}
    for s in banks:
        sub = issues[(issues["issuer"] == s) & (issues["active"] == "Y") & (issues["debt_type"] == STRUCTURED)] if len(issues) else issues
        if len(sub):
            top = sub.sort_values("eur", ascending=False).iloc[0]
            big[s], notes[s] = float(top["eur"]), f"{s}: {top['isin']}"
    line("bbg_big", "Largest structured or private note in Bloomberg", big, data=True, note="Check a note that is far larger than the rest before you use the total. " + "; ".join(notes.values()))
    state["r"] += 1

    # F. one summary table for each bank: instrument, issued, eligible, % of TREA. Formulas on the rows above.
    for s in banks:
        c = cols[s]
        tl, cc = bridge[s]["tlac"], bridge[s]["cc2"]
        mapped = ((tl.get("t2") or 0.0) + (tl.get("t2_am") or 0.0)) <= (cc.get("sub") or 0.0) + 1e-6  # the Tier 2 of the bank sits in its subordinated line
        r0 = state["r"]
        for j, v in enumerate([f"F. {s}: summary by instrument, EUR m ({bridge[s]['date']})", "Issued", "MREL-eligible", "% of TREA"], start=1):
            h = ws.cell(row=r0, column=j, value=v)
            h.font, h.fill = HEAD_FONT, HEAD
            h.alignment = Alignment(horizontal="left" if j == 1 else "center")
        items = []
        if mapped:
            items.append(("Debt securities and fair-value liabilities (structured notes)", f"={R('cc2_debt', c)}+{R('cc2_fv', c)}", f"={R('snp', c)}+{R('nonsub', c)}"))
            items.append(("Subordinated notes", f"={R('cc2_sub', c)}", f"={R('t2', c)}+{R('t2am', c)}"))
        else:
            items.append(("Debt securities, fair-value liabilities, and subordinated debts (the Tier 2 sits in the debt lines)", f"={R('cc2_debt', c)}+{R('cc2_fv', c)}+{R('cc2_sub', c)}",
                          f"={R('snp', c)}+{R('nonsub', c)}+{R('t2', c)}+{R('t2am', c)}"))
        items.append(("Other equity instruments (AT1)", f"={R('cc2_at1', c)}+{R('at1_add', c)}", f"={R('at1', c)}"))
        first = r0 + 1
        for i, (label, issued, elig) in enumerate(items):
            rr = first + i
            ws.cell(row=rr, column=1, value=label)
            ws.cell(row=rr, column=2, value=issued).number_format = "#,##0.0"
            ws.cell(row=rr, column=3, value=elig).number_format = "#,##0.0"
            ws.cell(row=rr, column=4, value=f"=IF({R('trea', c)}>0,C{rr}/{R('trea', c)},0)").number_format = "0.00%"
        rt = first + len(items)
        extra = [("Total", f"=SUM(B{first}:B{rt - 1})", f"=SUM(C{first}:C{rt - 1})", True),
                 ("Less: deduction for own holdings of other banks' eligible instruments", None, f"={R('ded', c)}", False),
                 ("Eligible after deduction", None, f"=C{rt}+C{rt + 1}", True),
                 ("Plus: CET1", None, f"={R('cet1', c)}", False),
                 ("Total MREL (own funds and eligible liabilities)", None, f"=C{rt + 2}+C{rt + 3}", True)]
        for i, (label, issued, elig, bold) in enumerate(extra):
            rr = rt + i
            ws.cell(row=rr, column=1, value=label).font = BOLD if bold else Font()
            if issued:
                ws.cell(row=rr, column=2, value=issued).number_format = "#,##0.0"
            cell = ws.cell(row=rr, column=3, value=elig)
            cell.number_format = "#,##0.0"
            ws.cell(row=rr, column=4, value=f"=IF({R('trea', c)}>0,C{rr}/{R('trea', c)},0)").number_format = "0.00%"
            if bold:
                for j in (1, 2, 3, 4):
                    ws.cell(row=rr, column=j).font = BOLD
        state["r"] = rt + len(extra) + 1

    ws.column_dimensions["A"].width = 78
    for s in banks:
        ws.column_dimensions[cols[s]].width = 14
    ws.column_dimensions[get_column_letter(note_col)].width = 110
    ws.freeze_panes = "B4"

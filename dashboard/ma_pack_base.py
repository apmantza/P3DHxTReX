"""Shared parts of the deal pack sheets: styles, a row writer, and the fixed layout of the BIL forward block on sheet P&L (the sheet Merger links to it). No dependency on ma_workbook."""

from __future__ import annotations

from typing import Any

from openpyxl.styles import Alignment, Font, PatternFill

BLUE, GREEN, BOLD = Font(color="0000FF"), Font(color="006100"), Font(bold=True)
HEAD_FONT = Font(bold=True, color="FFFFFF")
HEAD = PatternFill("solid", fgColor="1F3864")
SECTION = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
WARN_FILL = PatternFill("solid", fgColor="FCE4D6")
FORMATS = {"pct": "0.0%", "pct2": "0.00%", "bn": "0.00", "m": "#,##0", "m1": "#,##0.0", "x": '0.00"x"', "bp": "0", "int": "0", "eps": "0.00", "text": "@", "flag": "0", "f3": "0.000"}

PNL_SHEET = "P&L"
PNL_SWITCH = "B4"  # 1 = BIL forward profit from the drivers, 0 = flat at the trailing profit
PNL_YC = ["C", "D", "E", "F"]  # columns of 2026E to 2029E on sheet P&L (column B holds the base year 2025A)
BIL_TOP = 8  # first row of the BIL forward block (row 6: years, row 7: section title)
BIL_KEYS = [
    "in_loan_g", "in_margin_bp", "in_fee_g", "in_cost_g", "in_cor_bp", "in_tax", "in_other",  # inputs of each year
    "gap1", "loans", "loans_avg", "dfr", "d_dfr", "irrbb_up", "irrbb_dn",  # drivers
    "gap2", "nii_vol", "nii_rate", "nii_margin", "nii", "fees", "other", "rev", "costs", "impair", "pbt", "tax", "np_drv", "np_flat", "np_sel", "gap3", "check_np",
]


def bil_row(key: str) -> int:
    return BIL_TOP + BIL_KEYS.index(key)


class Sheet:
    """Writes label and value rows of a sheet. Column A is the label, B to G the values, H the note. A row can be found again by its key."""

    def __init__(self, ws, widths: tuple[int, ...] = (66, 14, 14, 14, 14, 14, 14, 90)):
        self.ws, self.r, self.rows = ws, 1, {}
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w

    def skip(self, n: int = 1) -> None:
        self.r += n

    def title(self, text: str) -> None:
        self.ws[f"A{self.r}"] = text
        self.ws[f"A{self.r}"].font = Font(bold=True, size=13)
        self.r += 1

    def text(self, text: str, bold: bool = False, fill: PatternFill | None = None) -> None:
        c = self.ws[f"A{self.r}"]
        c.value = text
        c.alignment = Alignment(wrap_text=False, vertical="top")
        if bold:
            c.font = BOLD
        if fill:
            c.fill = fill
        self.r += 1

    def head(self, labels: list[str]) -> None:
        for j, lab in enumerate(labels):
            c = self.ws.cell(row=self.r, column=1 + j, value=lab)
            c.font, c.fill = HEAD_FONT, HEAD
            c.alignment = Alignment(horizontal="left" if j == 0 else "center", wrap_text=True)
        self.r += 1

    def section(self, text: str, ncols: int = 8) -> None:
        for j in range(ncols):
            self.ws.cell(row=self.r, column=1 + j).fill = SECTION
        self.ws[f"A{self.r}"] = text
        self.ws[f"A{self.r}"].font = BOLD
        self.r += 1

    def row(self, key: str | None, label: str, values: list[Any], fmt: str | list[str] | None = None, note: str = "", roles: str | list[str | None] | None = None, bold: bool = False) -> int:
        """values go to columns B, C, ... A value that is a number or text is data (role 'data': green) unless the role says input (blue on yellow). A string that starts with = is a formula."""
        r = self.r
        self.ws[f"A{r}"] = label
        if bold:
            self.ws[f"A{r}"].font = BOLD
        for j, v in enumerate(values):
            if v is None:
                continue
            c = self.ws.cell(row=r, column=2 + j, value=v)
            f = fmt[j] if isinstance(fmt, list) else fmt
            if f:
                c.number_format = FORMATS.get(f, f)
            role = (roles[j] if j < len(roles) else None) if isinstance(roles, list) else roles
            if role == "input":
                c.font, c.fill = BLUE, INPUT_FILL
            elif role == "data":
                c.font = GREEN
            elif bold:
                c.font = BOLD
        if note:
            self.ws[f"H{r}"] = note
        if key:
            self.rows[key] = r
        self.r += 1
        return r

    def ref(self, key: str, col: str = "B", absolute: bool = False) -> str:
        return f"${col}${self.rows[key]}" if absolute else f"{col}{self.rows[key]}"

"""A small evaluator for Excel formulas. It runs the formulas of the M&A workbook in Python.

The M&A page and the M&A workbook use one set of formulas. This module reads the formulas from an openpyxl
workbook (or from a dict of cells) and computes the values. It supports the functions that the model uses:
SUM, AVERAGE, MAX, MIN, IF, IFERROR, CHOOSE, COUNT, MEDIAN, SMALL, SLOPE, INTERCEPT, RSQ, ABS, AND, OR, NOT, ROUND, TEXT. It has no Streamlit code.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable

TOKEN = re.compile(r"""
    \s*(?:
      (?P<str>"(?:[^"]|"")*")
    | (?P<func>[A-Za-z_][A-Za-z0-9_.]*)(?=\()
    | (?P<ref>(?:(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
    | (?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)
    | (?P<op><=|>=|<>|[-+*/^&=<>(),%])
    )""", re.X)
CELL = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")


class XlError(Exception):
    """An Excel error value, for example #DIV/0!."""

    def __init__(self, code: str = "#VALUE!"):
        super().__init__(code)
        self.code = code


def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def num_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def tokenize(text: str) -> list[tuple[str, str]]:
    pos, out = 0, []
    text = text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot parse formula at {text[pos:pos + 20]!r}: {text!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class Parser:
    """Recursive descent parser with the operator order of Excel."""

    def __init__(self, tokens: list[tuple[str, str]], sheet: str):
        self.t, self.i, self.sheet = tokens, 0, sheet

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        node = self.compare()
        if self.i != len(self.t):
            raise ValueError(f"unexpected token {self.peek()}")
        return node

    def compare(self):
        left = self.concat()
        while self.peek()[0] == "op" and self.peek()[1] in ("=", "<", ">", "<=", ">=", "<>"):
            op = self.take()[1]
            left = ("bin", op, left, self.concat())
        return left

    def concat(self):
        left = self.add()
        while self.peek() == ("op", "&"):
            self.take()
            left = ("bin", "&", left, self.add())
        return left

    def add(self):
        left = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            left = ("bin", op, left, self.mul())
        return left

    def mul(self):
        left = self.power()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            left = ("bin", op, left, self.power())
        return left

    def power(self):
        left = self.unary()
        while self.peek() == ("op", "^"):
            self.take()
            left = ("bin", "^", left, self.unary())
        return left

    def unary(self):
        if self.peek()[0] == "op" and self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            operand = self.unary()
            return ("neg", operand) if op == "-" else operand
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while self.peek() == ("op", "%"):
            self.take()
            node = ("bin", "/", node, ("num", 100.0))
        return node

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", float(val))
        if kind == "str":
            return ("str", val[1:-1].replace('""', '"'))
        if kind == "ref":
            return self.ref(val)
        if kind == "func":
            self.take()  # (
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.compare())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.compare())
            if self.take() != ("op", ")"):
                raise ValueError("missing )")
            return ("func", val.upper(), args)
        if (kind, val) == ("op", "("):
            node = self.compare()
            if self.take() != ("op", ")"):
                raise ValueError("missing )")
            return node
        raise ValueError(f"unexpected token {kind} {val}")

    def ref(self, text: str):
        sheet = self.sheet
        if "!" in text:
            sheet, text = text.rsplit("!", 1)
            sheet = sheet.strip("'")
        if ":" in text:
            a, b = text.split(":")
            ma, mb = CELL.match(a), CELL.match(b)
            return ("range", sheet, col_to_num(ma.group(1)), int(ma.group(2)), col_to_num(mb.group(1)), int(mb.group(2)))
        m = CELL.match(text)
        return ("cell", sheet, m.group(1) + m.group(2))


def num(x: Any) -> float:
    if isinstance(x, XlError):
        raise x
    if x is None or x == "":
        return 0.0
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except ValueError:
        raise XlError("#VALUE!")


def to_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return "TRUE" if x else "FALSE"
    if isinstance(x, float):
        return str(int(x)) if x == int(x) else repr(x)
    return str(x)


def excel_text(x: Any, fmt: str) -> str:
    v = num(x)
    sections = fmt.split(";")
    sec = sections[0] if v >= 0 or len(sections) == 1 else sections[1]
    if v < 0 and len(sections) == 1:
        sec = "-" + sec
    pct = "%" in sec
    if pct:
        v *= 100
    m = re.search(r"0(?:\.(0+))?", sec)
    if not m:
        return sec
    dec = len(m.group(1)) if m.group(1) else 0
    mag = abs(v) if (len(sections) > 1 and v < 0) else v
    scaled = math.floor(abs(mag) * 10 ** dec + 0.5 + 1e-9) / 10 ** dec
    body = f"{scaled:.{dec}f}"
    if mag < 0 and scaled != 0:
        body = "-" + body
    return sec[:m.start()] + body + sec[m.end():]


def flat(args: list[Any]) -> list[Any]:
    out: list[Any] = []
    for a in args:
        if isinstance(a, list):
            out.extend(a)
        else:
            out.append(a)
    return out


def numbers_in(args: list[Any]) -> list[float]:
    vals = []
    for a in args:
        if isinstance(a, list):
            for x in a:
                if isinstance(x, XlError):
                    raise x
                if isinstance(x, (int, float)) and not isinstance(x, bool):
                    vals.append(float(x))
        else:
            vals.append(num(a))
    return vals


class Model:
    """Cells of a workbook. A cell is a number, a string, None, or a formula string that starts with =."""

    def __init__(self, cells: dict[tuple[str, str], Any]):
        self.cells = cells
        self._ast: dict[tuple[str, str], Any] = {}

    @classmethod
    def from_openpyxl(cls, wb) -> "Model":
        cells = {}
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if c.value is not None:
                        cells[(ws.title, c.coordinate)] = c.value
        return cls(cells)

    def ast(self, key: tuple[str, str]):
        if key not in self._ast:
            raw = self.cells[key]
            self._ast[key] = Parser(tokenize(raw[1:]), key[0]).parse()
        return self._ast[key]

    def run(self, overrides: dict[tuple[str, str], Any] | None = None) -> "Run":
        return Run(self, overrides or {})

    def evaluate_all(self, overrides=None) -> dict[tuple[str, str], Any]:
        r = self.run(overrides)
        return {k: r.get(*k) for k in self.cells}


class Run:
    """One evaluation. It computes a cell when it is asked and keeps the result."""

    def __init__(self, model: Model, overrides: dict[tuple[str, str], Any]):
        self.m, self.o, self.cache = model, overrides, {}
        self.stack: set[tuple[str, str]] = set()

    def get(self, sheet: str, coord: str) -> Any:
        key = (sheet, coord)
        if key in self.cache:
            return self.cache[key]
        if key in self.o:
            val = self.o[key]
        elif key in self.m.cells:
            raw = self.m.cells[key]
            if isinstance(raw, str) and raw.startswith("="):
                if key in self.stack:
                    raise ValueError(f"circular reference at {key}")
                self.stack.add(key)
                try:
                    val = self.ev(self.m.ast(key))
                except XlError as e:
                    val = e
                except ZeroDivisionError:
                    val = XlError("#DIV/0!")
                finally:
                    self.stack.discard(key)
            else:
                val = raw
        else:
            val = None
        self.cache[key] = val
        return val

    def number(self, sheet: str, coord: str) -> float:
        v = self.get(sheet, coord)
        return float("nan") if isinstance(v, XlError) or v is None or isinstance(v, str) else float(v)

    def ev(self, n):
        k = n[0]
        if k == "num" or k == "str":
            return n[1]
        if k == "cell":
            v = self.get(n[1], n[2])
            if isinstance(v, XlError):
                raise v
            return v
        if k == "range":
            _, sh, c1, r1, c2, r2 = n
            return [self.get(sh, f"{num_to_col(c)}{r}") for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        if k == "neg":
            return -num(self.ev(n[1]))
        if k == "bin":
            op, a, b = n[1], self.ev(n[2]), self.ev(n[3])
            if op == "&":
                return to_text(a) + to_text(b)
            if op in ("=", "<>", "<", ">", "<=", ">="):
                if isinstance(a, str) or isinstance(b, str):
                    x, y = to_text(a).lower(), to_text(b).lower()
                else:
                    x, y = num(a), num(b)
                return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
            x, y = num(a), num(b)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    raise XlError("#DIV/0!")
                return x / y
            if op == "^":
                try:
                    return x ** y
                except (OverflowError, ZeroDivisionError, ValueError):
                    raise XlError("#NUM!")
        if k == "func":
            return self.func(n[1], n[2])
        raise ValueError(f"unknown node {n}")

    def func(self, name: str, args):
        if name == "IF":
            cond = self.ev(args[0])
            truth = bool(num(cond)) if not isinstance(cond, bool) else cond
            if truth:
                return self.ev(args[1]) if len(args) > 1 else True
            return self.ev(args[2]) if len(args) > 2 else False
        if name == "CHOOSE":
            i = int(num(self.ev(args[0])))
            if not 1 <= i < len(args):
                raise XlError("#VALUE!")
            return self.ev(args[i])
        if name == "IFERROR":
            try:
                return self.ev(args[0])
            except (XlError, ZeroDivisionError):
                return self.ev(args[1])
        vals = [self.ev(a) for a in args]
        if name == "SUM":
            return sum(numbers_in(vals))
        if name == "AVERAGE":
            v = numbers_in(vals)
            if not v:
                raise XlError("#DIV/0!")
            return sum(v) / len(v)
        if name == "MAX":
            v = numbers_in(vals)
            return max(v) if v else 0.0
        if name == "MIN":
            v = numbers_in(vals)
            return min(v) if v else 0.0
        if name == "COUNT":
            return float(len(numbers_in(vals)))
        if name == "MEDIAN":
            v = sorted(numbers_in(vals))
            if not v:
                raise XlError("#NUM!")
            mid = len(v) // 2
            return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
        if name == "SMALL":
            v = sorted(numbers_in([vals[0]]))
            k = int(num(vals[1]))
            if not 1 <= k <= len(v):
                raise XlError("#NUM!")
            return v[k - 1]
        if name in ("SLOPE", "INTERCEPT", "RSQ"):
            ys = [x for x in vals[0]] if isinstance(vals[0], list) else [vals[0]]
            xs = [x for x in vals[1]] if isinstance(vals[1], list) else [vals[1]]
            pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool) and not isinstance(y, bool)]
            n = len(pairs)
            if n < 2:
                raise XlError("#DIV/0!")
            mx, my = sum(p[0] for p in pairs) / n, sum(p[1] for p in pairs) / n
            sxx = sum((p[0] - mx) ** 2 for p in pairs)
            sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
            syy = sum((p[1] - my) ** 2 for p in pairs)
            if sxx == 0 or (name == "RSQ" and syy == 0):
                raise XlError("#DIV/0!")
            if name == "SLOPE":
                return sxy / sxx
            if name == "INTERCEPT":
                return my - sxy / sxx * mx
            return sxy * sxy / (sxx * syy)
        if name == "ABS":
            return abs(num(vals[0]))
        if name == "AND":
            return all(bool(num(x)) for x in flat(vals))
        if name == "OR":
            return any(bool(num(x)) for x in flat(vals))
        if name == "NOT":
            return not bool(num(vals[0]))
        if name == "ROUND":
            d = int(num(vals[1])) if len(vals) > 1 else 0
            x = num(vals[0])
            return math.copysign(math.floor(abs(x) * 10 ** d + 0.5) / 10 ** d, x)
        if name == "TEXT":
            return excel_text(vals[0], to_text(vals[1]))
        raise ValueError(f"function {name} is not supported")

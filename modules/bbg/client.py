"""Bloomberg API client. It counts the unique securities that the project requests each month.

Bloomberg limits the data of a terminal (hits per day and unique securities per month). The client records each
security that it requests in the table bbg_security_use. It stops with BudgetExceeded when a request would pass
the monthly budget. It also stops when Bloomberg answers with a limit message.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import time
from typing import Any, Iterable

try:
    import blpapi
except ImportError:  # the maths, the tests, and the readers of the tables need no Bloomberg
    blpapi = None

LIMIT_WORDS = ("limit", "capacity", "quota", "exceed")


class BudgetExceeded(RuntimeError):
    """The request would pass the monthly budget of unique securities."""


class LimitReached(RuntimeError):
    """Bloomberg reports that a data limit is reached."""


def py(e) -> Any:
    """Convert an element of a Bloomberg message to a Python value. Arrays and sequences become lists and dicts."""
    if e.isNull():
        return None
    if e.isArray():
        return [py(e.getValueAsElement(i)) for i in range(e.numValues())]
    if e.isComplexType():
        return {str(e.getElement(i).name()): py(e.getElement(i)) for i in range(e.numElements())}
    return e.getValue()


def iso(v: Any) -> Any:
    """Dates and times as text. Other values unchanged."""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:10]
    return v


class Client:
    def __init__(self, conn: sqlite3.Connection | None = None, budget: int = 4500, host: str = "localhost", port: int = 8194, log=print):
        self.conn, self.budget, self.log = conn, budget, log
        if blpapi is None:
            raise RuntimeError("blpapi is not installed. Use the Python of the blauto project.")
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        self.session = blpapi.Session(opts)
        if not self.session.start():
            raise RuntimeError("Bloomberg session did not start. Start the terminal.")
        for svc in ("//blp/refdata", "//blp/instruments"):
            if not self.session.openService(svc):
                raise RuntimeError(f"Bloomberg service {svc} did not open")
        self.ref_svc = self.session.getService("//blp/refdata")
        self.ins_svc = self.session.getService("//blp/instruments")
        if conn is not None:
            conn.execute("CREATE TABLE IF NOT EXISTS bbg_security_use (month TEXT, security TEXT, PRIMARY KEY (month, security)) WITHOUT ROWID")

    # ------------------------------------------------------------------------------ budget
    def month(self) -> str:
        return dt.date.today().strftime("%Y-%m")

    def used(self) -> int:
        if self.conn is None:
            return 0
        return self.conn.execute("SELECT COUNT(*) FROM bbg_security_use WHERE month = ?", (self.month(),)).fetchone()[0]

    def charge(self, securities: Iterable[str]) -> None:
        if self.conn is None:
            return
        m = self.month()
        known = {r[0] for r in self.conn.execute("SELECT security FROM bbg_security_use WHERE month = ?", (m,))}
        new = [s for s in dict.fromkeys(securities) if s not in known]
        if len(known) + len(new) > self.budget:
            raise BudgetExceeded(f"{len(known)} securities used this month, {len(new)} new, budget {self.budget}")
        self.conn.executemany("INSERT OR IGNORE INTO bbg_security_use VALUES (?, ?)", [(m, s) for s in new])
        self.conn.commit()

    # ------------------------------------------------------------------------------ messages
    def _collect(self, timeout: int = 90000) -> list:
        msgs: list = []
        while True:
            ev = self.session.nextEvent(timeout)
            msgs.extend(list(ev))
            et = ev.eventType()
            if et == blpapi.Event.RESPONSE:
                return msgs
            if et == blpapi.Event.TIMEOUT:
                raise TimeoutError("Bloomberg did not answer in time")
            for m in ev:
                if m.messageType() in (blpapi.Name("SessionTerminated"), blpapi.Name("ServiceDownEvent")):
                    raise RuntimeError("Bloomberg session ended")

    def _send(self, req) -> list:
        last: Exception | None = None
        for attempt in range(3):
            try:
                self.session.sendRequest(req)
                return self._collect()
            except TimeoutError as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]

    @staticmethod
    def _check_limit(text: str) -> None:
        low = text.lower()
        if any(w in low for w in LIMIT_WORDS) and ("data" in low or "daily" in low or "monthly" in low or "capacity" in low):
            raise LimitReached(text)

    @classmethod
    def _response_error(cls, err) -> RuntimeError:
        """The error of a failed request. Bloomberg marks its data limit with category LIMIT (code -4002) and the text 'Workflow review needed', which holds no limit word,
        so the category decides. Raises LimitReached for it. Returns the error to raise for any other failure."""
        msg = err.getElementAsString("message")
        category = err.getElementAsString("category") if err.hasElement("category") else ""
        code = err.getElementAsString("code") if err.hasElement("code") else ""
        if category.upper() == "LIMIT":
            raise LimitReached(f"Bloomberg data limit (category LIMIT, code {code}): {msg.strip()}. Check DAPI<GO> on the terminal. The limit is per month.")
        cls._check_limit(msg)
        return RuntimeError(msg)

    # ------------------------------------------------------------------------------ reference data
    def ref(self, securities: list[str], fields: list[str], overrides: dict[str, Any] | None = None, chunk: int = 100, fchunk: int = 25) -> dict[str, dict[str, Any]]:
        """Static and snapshot fields. Returns {security: {field: value}}. A failed security has the key _error."""
        secs = list(dict.fromkeys(securities))
        self.charge(secs)
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(secs), chunk):
            part = secs[i:i + chunk]
            for j in range(0, len(fields), fchunk):
                for sec, row in self._ref_once(part, fields[j:j + fchunk], overrides).items():
                    out.setdefault(sec, {}).update(row)
        return out

    def _ref_once(self, secs: list[str], fields: list[str], overrides: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        req = self.ref_svc.createRequest("ReferenceDataRequest")
        for s in secs:
            req.getElement("securities").appendValue(s)
        for f in fields:
            req.getElement("fields").appendValue(f)
        for k, v in (overrides or {}).items():
            o = req.getElement("overrides").appendElement()
            o.setElement("fieldId", k)
            o.setElement("value", str(v))
        out: dict[str, dict[str, Any]] = {}
        for m in self._send(req):
            if not m.hasElement("securityData"):
                if m.hasElement("responseError"):
                    raise self._response_error(m.getElement("responseError"))
                continue
            arr = m.getElement("securityData")
            for i in range(arr.numValues()):
                sd = arr.getValueAsElement(i)
                key = sd.getElementAsString("security")
                if sd.hasElement("securityError"):
                    msg = sd.getElement("securityError").getElementAsString("message")
                    self._check_limit(msg)
                    out[key] = {"_error": msg[:120]}
                    continue
                fd = sd.getElement("fieldData")
                out[key] = {f: (iso(py(fd.getElement(f))) if fd.hasElement(f) else None) for f in fields}
        return out

    # ------------------------------------------------------------------------------ history
    def hist(self, securities: list[str], fields: list[str], start: str, end: str, periodicity: str = "DAILY", currency: str | None = None,
             overrides: dict[str, Any] | None = None, chunk: int = 5, fiscal: bool = False, calendar_fill: bool = False) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        """History. Dates as YYYYMMDD. Returns {security: [(date, {field: value})]}."""
        secs = list(dict.fromkeys(securities))
        self.charge(secs)
        out: dict[str, list] = {}
        for i in range(0, len(secs), chunk):
            part = secs[i:i + chunk]
            req = self.ref_svc.createRequest("HistoricalDataRequest")
            for s in part:
                req.getElement("securities").appendValue(s)
            for f in fields:
                req.getElement("fields").appendValue(f)
            req.set("startDate", start)
            req.set("endDate", end)
            req.set("periodicitySelection", periodicity)
            if currency:
                req.set("currency", currency)
            if fiscal:
                req.set("periodicityAdjustment", "FISCAL")
            if calendar_fill:
                req.set("nonTradingDayFillOption", "ALL_CALENDAR_DAYS")
                req.set("nonTradingDayFillMethod", "PREVIOUS_VALUE")
            for k, v in (overrides or {}).items():
                o = req.getElement("overrides").appendElement()
                o.setElement("fieldId", k)
                o.setElement("value", str(v))
            for m in self._send(req):
                if m.hasElement("responseError"):
                    raise self._response_error(m.getElement("responseError"))
                if not m.hasElement("securityData"):
                    continue
                sd = m.getElement("securityData")
                key = sd.getElementAsString("security")
                if sd.hasElement("securityError"):
                    self._check_limit(sd.getElement("securityError").getElementAsString("message"))
                    out.setdefault(key, [])
                    continue
                fd = sd.getElement("fieldData")
                rows = out.setdefault(key, [])
                for k in range(fd.numValues()):
                    r = fd.getValueAsElement(k)
                    rows.append((iso(r.getElementAsDatetime("date")), {f: (iso(py(r.getElement(f))) if r.hasElement(f) else None) for f in fields}))
        return out

    # ------------------------------------------------------------------------------ instrument search
    def search(self, query: str, yellow_key: str = "YK_FILTER_CORP", max_results: int = 1000) -> list[tuple[str, str]]:
        req = self.ins_svc.createRequest("instrumentListRequest")
        req.set("query", query)
        req.set("yellowKeyFilter", yellow_key)
        req.set("languageOverride", "LANG_OVERRIDE_NONE")
        req.set("maxResults", max_results)
        res: list[tuple[str, str]] = []
        for m in self._send(req):
            if m.hasElement("results"):
                r = m.getElement("results")
                for i in range(r.numValues()):
                    x = r.getValueAsElement(i)
                    res.append((x.getElementAsString("security"), x.getElementAsString("description")))
        return res

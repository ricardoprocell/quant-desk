"""Quant Desk - data layer. Every fetcher returns (data, meta) with meta = {"source": "LIVE"|"DEMO", "asof": str, "note": str}.
Live fetchers never raise: on any failure they return DEMO data and put the reason in meta["note"]."""
from __future__ import annotations
import io
import datetime as dt
import numpy as np
import pandas as pd

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={ids}&cosd={start}"   # cosd limits history: the full file is several MB and very slow
UST = {"DGS1MO": 1 / 12, "DGS3MO": 0.25, "DGS6MO": 0.5, "DGS1": 1, "DGS2": 2, "DGS3": 3, "DGS5": 5,
       "DGS7": 7, "DGS10": 10, "DGS20": 20, "DGS30": 30}
UST_LABEL = {"DGS1MO": "1M", "DGS3MO": "3M", "DGS6MO": "6M", "DGS1": "1Y", "DGS2": "2Y", "DGS3": "3Y", "DGS5": "5Y",
             "DGS7": "7Y", "DGS10": "10Y", "DGS20": "20Y", "DGS30": "30Y"}


# ------------------------------------------------------------------ resilient cache (shared by all sessions of the server)
import functools, threading, time as _time
_CACHE: dict = {}
_LAST_LIVE: dict = {}
_LOCK = threading.Lock()


def _meta_of(res):
    for x in (res if isinstance(res, tuple) else (res,)):
        if isinstance(x, dict) and "source" in x:
            return x
    return None


def _cached(ok=600, fail=60):
    """Cache LIVE results for `ok` seconds and DEMO fallbacks for only `fail` seconds, so a transient outage heals fast.
    If a live fetch fails but an earlier live result exists, that result is served (flagged as stale) instead of DEMO."""
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            key = (fn.__name__, repr(a), repr(sorted(k.items())))
            now = _time.time()
            with _LOCK:
                hit = _CACHE.get(key)
                if hit and now < hit[0]:
                    return hit[1]
            res = fn(*a, **k)
            m = _meta_of(res)
            if m is not None and m["source"] == "LIVE":
                with _LOCK:
                    _LAST_LIVE[key] = res
                    _CACHE[key] = (now + ok, res)
                return res
            with _LOCK:
                prev = _LAST_LIVE.get(key)
            if prev is not None:
                pm = dict(_meta_of(prev))
                pm["note"] = str(pm.get("note", "")) + " · refresh failed, showing last live snapshot"
                out = tuple(pm if x is _meta_of(prev) else x for x in prev) if isinstance(prev, tuple) else prev
                with _LOCK:
                    _CACHE[key] = (now + fail, out)
                return out
            with _LOCK:
                _CACHE[key] = (now + fail, res)
            return res
        return wrap
    return deco


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def _retry(fn, tries=2, pause=0.8):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            _time.sleep(pause * (i + 1))
    raise last


# ------------------------------------------------------------------ server-side snapshot (Yahoo often blocks cloud IPs)
# A scheduled GitHub Action (snapshot.py) fetches Yahoo/FRED from its own IP and publishes data/snapshot.json on the `data` branch.
# Set SNAPSHOT_URL to its raw address. While it is the placeholder, the snapshot layer is skipped and only direct fetching is used.
SNAPSHOT_URL = "https://raw.githubusercontent.com/YOUR_GITHUB_USER/quant-desk/data/snapshot.json"
SNAPSHOT_MAX_AGE_H = 96          # Friday close must still serve on Monday morning


def _snapshot_url():
    """QD_SNAPSHOT_URL env var > owner/repo read from the deployed clone's .git/config > the constant above."""
    import os
    import re
    from pathlib import Path
    if os.environ.get("QD_SNAPSHOT_URL"):
        return os.environ["QD_SNAPSHOT_URL"]
    try:
        import streamlit as st
        if st.secrets.get("QD_SNAPSHOT_URL"):
            return str(st.secrets["QD_SNAPSHOT_URL"])
    except Exception:  # noqa: BLE001
        pass
    try:
        for base in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents[:3]]:
            cfg = base / ".git" / "config"
            if cfg.exists():
                m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$", cfg.read_text(), re.M)
                if m:
                    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/data/snapshot.json"
    except Exception:  # noqa: BLE001
        pass
    return SNAPSHOT_URL


def _snap():
    import os
    if os.environ.get("QD_NO_SNAPSHOT") or "YOUR_GITHUB_USER" in _snapshot_url():
        return None
    return _snap_cached()


@_cached(ok=300, fail=60)
def _snap_cached():
    try:
        import json
        d = _get_ok(_snapshot_url(), 10).json()
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(d["generated_utc"])).total_seconds() / 3600
        d["_age_h"] = age
        ok = age <= SNAPSHOT_MAX_AGE_H
        return d if ok else None, _meta("LIVE" if ok else "DEMO", "snapshot")
    except Exception as e:  # noqa: BLE001
        return None, _meta("DEMO", f"snapshot unavailable: {type(e).__name__}: {str(e)[:80]}")


def diagnostics():
    """Plain-language state of the data layer, for the sidebar."""
    url = _snapshot_url()
    d = {"snapshot_url": url, "configured": "YOUR_GITHUB_USER" not in url}
    if not d["configured"]:
        d["status"] = "not configured (placeholder URL)"
        return d
    r = _snap_cached()
    if r[0]:
        d["status"] = f"ok · generated {r[0]['generated_utc'][:16].replace('T', ' ')} UTC · {r[0]['_age_h']:.1f} h old"
        d["sections"] = {"curve": bool(r[0].get("curve")), "commodities": list(r[0].get("commodities", {})), "tickers": list(r[0].get("underlyings", {}))}
    else:
        d["status"] = "unreachable or too old: " + str(r[1].get("note"))
    return d


def _snap_data():
    r = _snap()
    return r[0] if r else None


def _snap_note(d, what):
    t = d["generated_utc"][:16].replace("T", " ")
    return f"{what} · server snapshot {t} UTC (direct fetch blocked from this host)"


def _meta(src, note="", asof=None):
    return {"source": src, "asof": asof or dt.date.today().isoformat(), "note": note}


# ----------------------------------------------------------------------------- curve
def demo_curve():
    """Illustrative USD curve (NOT market data)."""
    q = {"SOFR": 0.0365, "DGS1MO": 0.0368, "DGS3MO": 0.0362, "DGS6MO": 0.0352, "DGS1": 0.0345, "DGS2": 0.0348,
         "DGS3": 0.0356, "DGS5": 0.0372, "DGS7": 0.0392, "DGS10": 0.0412, "DGS20": 0.0462, "DGS30": 0.0470}
    return q


def _get_ok(url, timeout):
    import requests
    r = requests.get(url, timeout=(5, timeout), headers={"User-Agent": "Mozilla/5.0 (QuantDesk)"})
    r.raise_for_status()
    return r


FRED_ONE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                "?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
NYFED_SOFR = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json"
_TSY_COLS = {"1 mo": "DGS1MO", "3 mo": "DGS3MO", "6 mo": "DGS6MO", "1 yr": "DGS1", "2 yr": "DGS2", "3 yr": "DGS3", "5 yr": "DGS5",
             "7 yr": "DGS7", "10 yr": "DGS10", "20 yr": "DGS20", "30 yr": "DGS30"}


def _curve_fred(timeout):
    """One small request per series, in parallel (the combined 12-series request is slow and often times out)."""
    from concurrent.futures import ThreadPoolExecutor
    start = (dt.date.today() - dt.timedelta(days=45)).isoformat()

    def one(i):
        r = _retry(lambda: _get_ok(FRED_ONE.format(id=i, start=start), timeout), tries=2, pause=1.0)
        df = pd.read_csv(io.StringIO(r.text), na_values=["."])
        sr = df.iloc[:, 1].dropna()
        return i, float(sr.iloc[-1]) / 100.0, str(df.iloc[sr.index[-1], 0])

    ids = list(UST) + ["SOFR"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = []
        for f in [ex.submit(one, i) for i in ids]:
            try:
                res.append(f.result(timeout=timeout * 2 + 5))
            except Exception:  # noqa: BLE001
                pass
    if len(res) < 6:
        raise ValueError(f"FRED returned {len(res)} of {len(ids)} series")
    return {i: v for i, v, _ in res}, max(d for _, _, d in res), "FRED: Treasury par yields + SOFR"


def _parse_treasury_csv(text):
    """US Treasury daily par yield curve CSV -> ({series_id: decimal}, date). Most recent row wins; values are in %."""
    df = pd.read_csv(io.StringIO(text))
    df.columns = [str(c).strip().lower() for c in df.columns]
    dcol = next(c for c in df.columns if c.startswith("date"))
    df["_d"] = pd.to_datetime(df[dcol], errors="coerce")
    df = df.dropna(subset=["_d"]).sort_values("_d")
    if df.empty:
        raise ValueError("Treasury CSV has no rows")
    row = df.iloc[-1]
    out = {sid: float(row[c]) / 100.0 for c, sid in _TSY_COLS.items() if c in df.columns and pd.notna(row[c])}
    return out, row["_d"].date().isoformat()


def _curve_treasury(timeout):
    q, asof, last = None, None, None
    for y in (dt.date.today().year, dt.date.today().year - 1):
        try:
            q, asof = _parse_treasury_csv(_retry(lambda y=y: _get_ok(TREASURY_URL.format(y=y), timeout), tries=2).text)
            break
        except Exception as e:  # noqa: BLE001
            last = e
    if not q or len(q) < 6:
        raise ValueError(f"Treasury.gov unavailable: {last}")
    try:
        js = _retry(lambda: _get_ok(NYFED_SOFR, timeout), tries=2).json()
        q["SOFR"] = float(js["refRates"][0]["percentRate"]) / 100.0
    except Exception:  # noqa: BLE001
        q["SOFR"] = q.get("DGS1MO", 0.04)      # proxy: 1M bill, flagged in the note
        return q, asof, "US Treasury par yields (SOFR proxy: 1M bill)"
    return q, asof, "US Treasury par yields + NY Fed SOFR"


@_cached(ok=600, fail=45)
def fetch_curve(timeout=20):
    """Latest Treasury par yields + SOFR. Tries FRED, then Treasury.gov + NY Fed, then the server snapshot, then DEMO."""
    errs = []
    for fn in (_curve_fred, _curve_treasury):
        try:
            q, asof, note = fn(timeout)
            return q, _meta("LIVE", note, asof), None
        except Exception as e:  # noqa: BLE001
            errs.append(f"{fn.__name__[7:]}: {type(e).__name__}: {str(e)[:60]}")
    sd = _snap_data()
    if sd and sd.get("curve", {}).get("quotes"):
        return sd["curve"]["quotes"], _meta("LIVE", _snap_note(sd, "Treasury/FRED"), sd["curve"].get("asof")), None
    return demo_curve(), _meta("DEMO", "live fetch failed (" + "; ".join(errs) + ")"), None


def curve_instruments(quotes, ois_override=None):
    """Quotes dict -> list of Instrument. Treasury <1Y bills and SOFR are deposits; >=1Y par bonds (semi-annual).
    ois_override: list of (tenor_years, rate) from pasted SOFR OIS swaps; replaces the Treasury par points >=1Y."""
    from qd_rates import Instrument
    ins = []
    if "SOFR" in quotes:
        ins.append(Instrument(1 / 365, "dep", quotes["SOFR"], "SOFR O/N"))
    for k, T in UST.items():
        if k in quotes and (T < 1 or not ois_override):
            ins.append(Instrument(T, "dep" if T < 1 else "par", quotes[k], UST_LABEL[k]))
    if ois_override:
        for T, rt in ois_override:
            if T >= 1:
                ins.append(Instrument(float(T), "par", float(rt), f"OIS {T:g}Y"))
    return ins


def parse_ois_text(text):
    """Parse 'tenor, rate%' lines, e.g. '2Y, 3.55' or '18M 3.6' or '5, 3.7'. Returns list[(years, decimal)]."""
    out = []
    for line in text.replace(";", "\n").splitlines():
        line = line.strip().replace("%", "")
        if not line:
            continue
        parts = line.replace(",", " ").replace("\t", " ").split()
        if len(parts) < 2:
            raise ValueError(f"Cannot read line: '{line}'")
        t = parts[0].upper()
        mult = 1 / 12 if t.endswith("M") else 1.0
        t = t.rstrip("YM")
        out.append((float(t) * mult, float(parts[1]) / 100.0))
    return sorted(out)


# ------------------------------------------------------------------- commodities
COMMODITIES = {
    "gold": {"spot": "GC=F", "root": "GC", "exch": "CMX", "months": "GJMQVZ", "unit": "USD/oz", "u": 0.005, "y": 0.0},
    "crude": {"spot": "CL=F", "root": "CL", "exch": "NYM", "months": "FGHJKMNQUVXZ", "unit": "USD/bbl", "u": 0.04, "y": 0.02},
}
_MC = "FGHJKMNQUVXZ"


def _approx_expiry(key, y, m):
    """Approximate last-trade date: crude (NYMEX CL) ~3 business days before the 25th of the PRECEDING month;
    gold (COMEX GC) ~3rd last business day of the contract month."""
    if key == "crude":
        return dt.date(y, m, 1) - dt.timedelta(days=10)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1 + 4)


def contract_list(key, n=6, today=None):
    c = COMMODITIES[key]
    today = today or dt.date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(48):
        code = _MC[m - 1]
        if code in c["months"]:
            exp = _approx_expiry(key, y, m)
            if (exp - today).days >= 3:                 # skip contracts that have already stopped trading
                out.append({"ticker": f"{c['root']}{code}{str(y)[2:]}.{c['exch']}", "expiry": exp, "T": (exp - today).days / 365.0})
                if len(out) == n:
                    break
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def demo_commodity(key):
    c = COMMODITIES[key]
    spot = 2650.0 if key == "gold" else 68.5
    r, u, y = 0.0375, c["u"], c["y"]
    rng = np.random.default_rng({"gold": 3, "crude": 4}[key])
    rows = []
    for k in contract_list(key):
        f = spot * np.exp((r + u - y) * k["T"]) * (1 + rng.normal(0, 0.0006 * (1 + k["T"] * 4)))
        rows.append({**k, "price": float(f)})
    return spot, pd.DataFrame(rows)


def _last_close(ticker, timeout=8):
    import yfinance as yf
    h = _retry(lambda: yf.Ticker(ticker).history(period="5d", timeout=timeout)["Close"].dropna(), tries=2, pause=0.5)
    return float(h.iloc[-1]) if len(h) else None


@_cached(ok=300, fail=45)
def fetch_commodity(key, n=6):
    sd = _snap_data()
    if sd and key in sd.get("commodities", {}):
        c = sd["commodities"][key]
        today = dt.date.today()
        rows = []
        for r in c["rows"]:
            e = dt.date.fromisoformat(r["expiry"])
            if (e - today).days >= 3:
                rows.append({"ticker": r["ticker"], "expiry": e, "T": (e - today).days / 365.0, "price": float(r["price"])})
        if c.get("spot") and len(rows) >= 2:
            return float(c["spot"]), pd.DataFrame(rows), _meta("LIVE", _snap_note(sd, "Yahoo futures"))
    try:
        from concurrent.futures import ThreadPoolExecutor
        c = COMMODITIES[key]
        cl = contract_list(key, n)
        with ThreadPoolExecutor(max_workers=7) as ex:
            f_spot = ex.submit(_last_close, c["spot"])
            f_fut = [ex.submit(_last_close, k["ticker"]) for k in cl]
            spot = f_spot.result(timeout=25)
            px = [f.result(timeout=25) for f in f_fut]
        if spot is None:
            raise ValueError("no spot quote")
        rows = [{**k, "price": p} for k, p in zip(cl, px) if p is not None]
        if len(rows) < 2:
            raise ValueError("no futures quotes returned")
        return spot, pd.DataFrame(rows), _meta("LIVE", f"yfinance: {c['spot']} + {len(rows)} contracts (spot = front continuous)")
    except Exception as e:  # noqa: BLE001
        s_, d = demo_commodity(key)
        return s_, d, _meta("DEMO", f"live fetch failed: {type(e).__name__}: {str(e)[:80]}")


# ------------------------------------------------------------------------ options
def demo_underlying(ticker="SPY"):
    rng = np.random.default_rng(abs(hash(ticker)) % 2 ** 32 if False else sum(map(ord, ticker)))
    n = 260
    ret = rng.normal(0.0004, 0.011, n)
    px = 100 * np.exp(np.cumsum(ret))
    px = px / px[-1] * (520.0 if ticker == "SPY" else 190.0)
    idx = pd.bdate_range(end=dt.date.today(), periods=n)
    return pd.Series(px, index=idx, name=ticker)


def demo_chain(S, T, atm=0.20, skew=-0.10, curv=0.35):
    """Synthetic smile chain (BSM mid prices) so the surface view works offline."""
    from qd_opt import bsm
    ks = np.round(S * np.linspace(0.8, 1.2, 17))
    rows = []
    for k in ks:
        m = np.log(k / S)
        iv = atm + skew * m + curv * m ** 2
        for cp in ("call", "put"):
            rows.append({"strike": float(k), "cp": cp, "mid": float(bsm(S, k, 0.04, 0.012, iv, T, cp)), "iv_true": iv})
    return pd.DataFrame(rows)


@_cached(ok=600, fail=45)
def fetch_underlying(ticker):
    """Returns (price Series, dividend yield, expiries list, meta). Falls back to DEMO."""
    sd = _snap_data()
    if sd and ticker in sd.get("underlyings", {}):
        u = sd["underlyings"][ticker]
        h = pd.Series([float(p) for _, p in u["closes"]], index=pd.to_datetime([d for d, _ in u["closes"]]), name=ticker)
        today = dt.date.today()
        exps = [e for e in u["expiries"] if dt.date.fromisoformat(e) > today]
        if len(h) >= 60 and exps:
            return h, float(u.get("q", 0.0)), exps, _meta("LIVE", _snap_note(sd, f"Yahoo {ticker}"), str(h.index[-1].date()))
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        h = tk.history(period="1y", timeout=10)["Close"].dropna()
        if len(h) < 60:
            raise ValueError("insufficient history")
        info = {}
        try:
            info = tk.fast_info
        except Exception:  # noqa: BLE001
            pass
        q = 0.0
        try:
            q = float(tk.info.get("dividendYield") or 0.0)
            q = q / 100 if q > 0.2 else q
        except Exception:  # noqa: BLE001
            pass
        try:
            exps = list(tk.options)
        except Exception:  # noqa: BLE001
            exps = []
        note = f"yfinance: {ticker}"
        if not exps:                      # Yahoo sometimes serves prices but blocks the option-expiry list
            today = dt.date.today()
            exps = [(today + dt.timedelta(days=d)).isoformat() for d in (30, 60, 90, 180)]
            note += " (expiries approximate: option list unavailable)"
        return h, q, exps, _meta("LIVE", note, str(h.index[-1].date()))
    except Exception as e:  # noqa: BLE001
        today = dt.date.today()
        exps = [(today + dt.timedelta(days=d)).isoformat() for d in (30, 60, 90, 180)]
        return demo_underlying(ticker), 0.012, exps, _meta("DEMO", f"live fetch failed: {type(e).__name__}: {str(e)[:80]}")


@_cached(ok=300, fail=45)
def fetch_chain(ticker, expiry, S, T):
    """Option chain for one expiry as DataFrame[strike,cp,mid,bid,ask,iv_mkt]; DEMO fallback."""
    sd = _snap_data()
    ch = (sd or {}).get("underlyings", {}).get(ticker, {}).get("chains", {}).get(expiry)
    if ch:
        df = pd.DataFrame(ch, columns=["strike", "cp", "mid"])
        df = df[(df.strike > 0.6 * S) & (df.strike < 1.4 * S)]
        if len(df) >= 6:
            return df.reset_index(drop=True), _meta("LIVE", _snap_note(sd, f"Yahoo chain {expiry}"))
    try:
        import yfinance as yf
        oc = yf.Ticker(ticker).option_chain(expiry)
        parts = []
        for cp, d in (("call", oc.calls), ("put", oc.puts)):
            x = d[["strike", "bid", "ask", "impliedVolatility", "openInterest"]].copy()
            x["cp"] = cp
            parts.append(x)
        df = pd.concat(parts)
        df["mid"] = np.where((df.bid > 0) & (df.ask > 0), (df.bid + df.ask) / 2, np.nan)
        df = df.dropna(subset=["mid"])
        df = df[(df.strike > 0.6 * S) & (df.strike < 1.4 * S)]
        if len(df) < 6:
            raise ValueError("thin chain")
        return df.reset_index(drop=True), _meta("LIVE", f"yfinance chain {expiry}")
    except Exception as e:  # noqa: BLE001
        return demo_chain(S, T), _meta("DEMO", f"live chain failed: {type(e).__name__}: {str(e)[:80]}")

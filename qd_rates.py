"""Quant Desk - interest-rate curve engine.

Curve construction from market instruments:
  * deposits / bills  ("dep"): simple-rate zero-coupon instruments, DF = 1 / (1 + q T)
  * par swaps / par bonds ("par"): fixed leg at `freq` payments a year priced at par,
        q * sum(alpha_i * DF(d_i)) + DF(T) = 1
Two interpolation schemes:
  * "loglinear": sequential bootstrap, ln DF linear between nodes (piecewise-flat forwards)
  * "smooth"   : global solve with a monotone cubic (PCHIP) through the zero rates (continuous forwards)
Single-curve discounting. Year fractions are 1/freq (no day-count conventions). Rates are decimals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq, root

CONVENTIONS = ["cc", "annual", "semi", "quarterly", "monthly", "simple"]
_M = {"annual": 1, "semi": 2, "quarterly": 4, "monthly": 12}


# ------------------------------------------------------------- rate <-> DF conversions
def df_to_rate(df, t, conv="cc"):
    df = np.asarray(df, float)
    t = np.maximum(np.asarray(t, float), 1e-12)
    if conv == "cc":
        out = -np.log(df) / t
    elif conv == "simple":
        out = (1.0 / df - 1.0) / t
    else:
        m = _M[conv]
        out = m * (df ** (-1.0 / (m * t)) - 1.0)
    return float(out) if np.ndim(out) == 0 else out


def rate_to_df(r, t, conv="cc"):
    r, t = np.asarray(r, float), np.asarray(t, float)
    if conv == "cc":
        out = np.exp(-r * t)
    elif conv == "simple":
        out = 1.0 / (1.0 + r * t)
    else:
        m = _M[conv]
        out = (1.0 + r / m) ** (-m * t)
    return float(out) if np.ndim(out) == 0 else out


def convert_rate(r, t, from_conv, to_conv):
    return df_to_rate(rate_to_df(r, t, from_conv), t, to_conv)


# ------------------------------------------------------------------------- schedules
def schedule(T, freq):
    """Payment dates (years) and accruals for a fixed leg ending at T, generated backwards from T."""
    n = int(np.ceil(T * freq - 1e-9))
    dates = np.sort(T - np.arange(n) / freq)
    dates = dates[dates > 1e-9]
    alpha = np.diff(np.r_[0.0, dates])
    return dates, alpha


@dataclass
class Instrument:
    tenor: float          # years
    kind: str             # "dep" | "par"
    quote: float          # decimal
    label: str = ""


# ----------------------------------------------------------------------------- curve
class Curve:
    """Discount curve defined by ln DF(t)."""

    def __init__(self, nodes_t, nodes_lndf=None, zero_nodes=None, method="loglinear", freq=2,
                 instruments=None, fallback=False):
        self.method, self.freq, self.fallback = method, freq, fallback
        self.instruments = list(instruments or [])
        if method == "smooth":
            self._tz = np.asarray(nodes_t, float)
            self._z = np.asarray(zero_nodes, float)
            self._pchip = PchipInterpolator(self._tz, self._z) if len(self._tz) > 1 else None
            self.tmax = float(self._tz[-1])
            h = 1e-4
            self._fwd_tail = float(-(self._lndf_core(self.tmax) - self._lndf_core(self.tmax - h)) / h)
        else:
            self._t = np.asarray(nodes_t, float)
            self._l = np.asarray(nodes_lndf, float)
            self.tmax = float(self._t[-1])
            self._slope = (self._l[-1] - self._l[-2]) / (self._t[-1] - self._t[-2]) if len(self._t) > 1 else 0.0

    # --- core
    def _zero_core(self, t):
        t = np.asarray(t, float)
        tc = np.clip(t, self._tz[0], self._tz[-1])
        return self._pchip(tc) if self._pchip is not None else np.full_like(tc, self._z[0])

    def _lndf_core(self, t):
        t = np.asarray(t, float)
        return -self._zero_core(t) * t

    def lndf(self, t):
        t = np.asarray(t, float)
        if self.method == "smooth":
            inside = self._lndf_core(np.minimum(t, self.tmax))
            ln = np.where(t <= self.tmax, inside, self._lndf_core(self.tmax) - self._fwd_tail * (t - self.tmax))
            # short end: flat zero rate before the first pillar
            return np.where(t < self._tz[0], -self._z[0] * t, ln)
        ln = np.interp(t, self._t, self._l)
        return np.where(t > self.tmax, self._l[-1] + self._slope * (t - self.tmax), ln)

    def df_at(self, t):
        out = np.exp(self.lndf(t))
        return float(out) if np.ndim(t) == 0 else out

    # --- derived quantities
    def zero(self, t, conv="cc"):
        return df_to_rate(self.df_at(t), t, conv)

    def forward(self, t1, t2, conv="cc"):
        d = self.df_at(t1) / self.df_at(t2)
        tau = t2 - t1
        if conv == "cc":
            return float(np.log(d) / tau)
        return float(df_to_rate(1.0 / d, tau, conv))

    def inst_forward(self, t):
        t = np.asarray(t, float)
        h = 1e-3
        out = -(self.lndf(t + h) - self.lndf(np.maximum(t - h, 0.0))) / (t + h - np.maximum(t - h, 0.0))
        return float(out) if np.ndim(t) == 0 else out

    def annuity(self, T, freq=None, start=0.0):
        d, a = schedule(T, freq or self.freq)
        return float(np.sum(a * self.df_at(start + d)))

    def par_rate(self, T, freq=None, start=0.0):
        return float((self.df_at(start) - self.df_at(start + T)) / self.annuity(T, freq, start))


# ---------------------------------------------------------------------- bootstrapping
def _prep(instruments):
    ins = sorted(instruments, key=lambda i: i.tenor)
    ts = [i.tenor for i in ins]
    if len(set(ts)) != len(ts):
        raise ValueError("Duplicate tenors in the instrument list.")
    if any(t <= 0 for t in ts):
        raise ValueError("Tenors must be positive.")
    return ins


def _loglinear(ins, freq):
    nt, nl = [0.0], [0.0]
    for i in ins:
        if i.kind == "dep":
            df = 1.0 / (1.0 + i.quote * i.tenor)
            if df <= 0:
                raise ValueError(f"Invalid deposit rate at {i.tenor:g}y.")
            nt.append(i.tenor)
            nl.append(float(np.log(df)))
            continue
        d, a = schedule(i.tenor, freq)

        def g(y, i=i, d=d, a=a):
            lnd = np.interp(d, np.array(nt + [i.tenor]), np.array(nl + [y]))
            df = np.exp(lnd)
            return i.quote * np.sum(a * df) + df[-1] - 1.0

        try:
            y = brentq(g, -60.0, 3.0, xtol=1e-15, rtol=1e-14, maxiter=300)
        except ValueError as e:
            raise ValueError(f"Bootstrap failed at {i.tenor:g}y: no positive discount factor reprices the instrument.") from e
        nt.append(i.tenor)
        nl.append(y)
    return np.array(nt), np.array(nl)


def build_curve(instruments, freq=2, method="loglinear") -> Curve:
    ins = _prep(instruments)
    if not ins:
        raise ValueError("Enter at least one market quote.")
    nt, nl = _loglinear(ins, freq)
    if method != "smooth":
        return Curve(nt, nl, method="loglinear", freq=freq, instruments=ins)
    tp = nt[1:]
    z0 = -nl[1:] / tp

    def resid(z):
        c = Curve(tp, zero_nodes=z, method="smooth", freq=freq)
        out = []
        for i in ins:
            if i.kind == "dep":
                out.append(c.df_at(i.tenor) - 1.0 / (1.0 + i.quote * i.tenor))
            else:
                d, a = schedule(i.tenor, freq)
                out.append(i.quote * np.sum(a * c.df_at(d)) + c.df_at(i.tenor) - 1.0)
        return np.array(out)

    if len(tp) < 2:
        return Curve(tp, zero_nodes=z0, method="smooth", freq=freq, instruments=ins)
    sol = root(resid, z0, method="hybr", tol=1e-13)
    if sol.success and np.max(np.abs(resid(sol.x))) < 1e-9:
        return Curve(tp, zero_nodes=sol.x, method="smooth", freq=freq, instruments=ins)
    return Curve(nt, nl, method="loglinear", freq=freq, instruments=ins, fallback=True)


def shock(curve: Curve, bumps_bp) -> Curve:
    """Rebuild the curve after bumping each market quote (bp, aligned with curve.instruments)."""
    b = np.asarray(bumps_bp, float) / 1e4
    ins = [Instrument(i.tenor, i.kind, i.quote + b[k], i.label) for k, i in enumerate(curve.instruments)]
    return build_curve(ins, curve.freq, "smooth" if curve.method == "smooth" and not curve.fallback else "loglinear")


# ----------------------------------------------------------------------- tables & stats
def grid_times(curve: Curve, step=None):
    step = step or 0.25
    return np.arange(step, curve.tmax + 1e-9, step)


def curve_table(curve: Curve, times):
    import pandas as pd
    t = np.asarray(times, float)
    df = curve.df_at(t)
    prev = curve.df_at(np.maximum(t - 1.0, 0.0))
    tau = np.minimum(t, 1.0)
    return pd.DataFrame({
        "t": t, "df": df,
        "par": [curve.par_rate(x, curve.freq) if x >= 1.0 / curve.freq else np.nan for x in t],
        "z_cc": df_to_rate(df, t, "cc"), "z_annual": df_to_rate(df, t, "annual"),
        "z_semi": df_to_rate(df, t, "semi"), "z_quarterly": df_to_rate(df, t, "quarterly"),
        "z_simple": df_to_rate(df, t, "simple"),
        "fwd_1y": (prev / df - 1.0) / tau,
        "fwd_inst": curve.inst_forward(t),
    })


def forward_matrix(curve: Curve, starts, tenors):
    import pandas as pd
    M = np.full((len(starts), len(tenors)), np.nan)
    for i, s in enumerate(starts):
        for j, n in enumerate(tenors):
            if s + n <= curve.tmax + 1e-9:
                M[i, j] = curve.par_rate(n, curve.freq, start=s)
    return pd.DataFrame(M, index=list(starts), columns=list(tenors))


def curve_stats(curve: Curve):
    """Level, slopes, curvature and forward anchors (bp / decimals), skipping anchors beyond the curve."""
    T = curve.tmax
    z = lambda x, c="cc": curve.zero(min(x, T), c)
    out = {"tmax": T}
    out["z2"], out["z10"], out["z30"] = z(2.0), z(10.0), z(30.0)
    out["s2s10s"] = (curve.par_rate(min(10, T)) - curve.par_rate(min(2, T))) * 1e4 if T >= 2 else np.nan
    out["s5s30s"] = (curve.par_rate(min(30, T)) - curve.par_rate(min(5, T))) * 1e4 if T >= 5 else np.nan
    out["s3m10y"] = (z(10.0, "simple" if False else "cc") - z(0.25, "cc")) * 1e4
    out["fly_2_5_10"] = (2 * curve.par_rate(min(5, T)) - curve.par_rate(min(2, T)) - curve.par_rate(min(10, T))) * 1e4 if T >= 10 else np.nan
    out["f1y1y"] = curve.forward(1.0, 2.0, "annual") if T >= 2 else np.nan
    out["f5y5y"] = curve.forward(5.0, 10.0, "annual") if T >= 10 else np.nan
    pg = np.array([curve.par_rate(x) for x in np.arange(1.0, T + 1e-9, 1.0)]) if T >= 1 else np.array([np.nan])
    out["min_fwd"] = float(np.min(curve.inst_forward(np.linspace(0.05, T, 200))))
    s = out["s2s10s"]
    if np.isnan(s):
        out["shape"] = "n/a"
    elif len(pg) > 3 and 0 < int(np.argmax(pg)) < len(pg) - 1 and (np.max(pg) - max(pg[0], pg[-1])) * 1e4 > 15:
        out["shape"] = "humped"
    elif s < -10:
        out["shape"] = "inverted"
    elif abs(s) <= 10:
        out["shape"] = "flat"
    elif s > 100:
        out["shape"] = "steep"
    else:
        out["shape"] = "normal"
    return out


# ------------------------------------------------------------------- instruments / risk
def swap_pv(curve: Curve, notional, fixed, T, freq, receive=True, start=0.0):
    """Single-curve swap value: fixed leg minus floating leg (floating = DF(start) - DF(start+T))."""
    A = curve.annuity(T, freq, start)
    v = notional * (fixed * A - (curve.df_at(start) - curve.df_at(start + T)))
    return v if receive else -v


def _pv_shocked(curve, fn, bumps):
    try:
        return fn(shock(curve, bumps))
    except ValueError:
        return np.nan


def parallel_dv01(curve, fn, bp=1.0):
    n = len(curve.instruments)
    return (_pv_shocked(curve, fn, -np.full(n, bp)) - _pv_shocked(curve, fn, np.full(n, bp))) / 2.0


def key_rate_dv01(curve, fn, bp=1.0):
    n = len(curve.instruments)
    out = []
    for k in range(n):
        b = np.zeros(n)
        b[k] = bp
        out.append((_pv_shocked(curve, fn, -b) - _pv_shocked(curve, fn, b)) / 2.0)
    return np.array(out)


def pnl_scenarios(curve, fn, scenarios):
    """scenarios: dict name -> bump vector (bp per instrument). Returns dict name -> PnL."""
    base = fn(curve)
    return {k: _pv_shocked(curve, fn, np.asarray(v, float)) - base for k, v in scenarios.items()}


SCENARIO_SHAPES = {
    "parallel_up": (1, 1, 0), "parallel_down": (-1, -1, 0),
    "steepener": (-0.5, 0.5, 0), "flattener": (0.5, -0.5, 0),
    "belly_up": (0, 0, 1), "belly_down": (0, 0, -1),
}


def scenario_bumps(tenors, short_bp, long_bp, belly_bp=0.0, belly_t=None, belly_w=None):
    t = np.asarray(tenors, float)
    lo, hi = t.min(), t.max()
    lin = np.full_like(t, short_bp) if hi <= lo else short_bp + (long_bp - short_bp) * (t - lo) / (hi - lo)
    if belly_bp == 0 or hi <= lo:
        return lin
    bt = belly_t if belly_t is not None else min(max(5.0, lo), hi)
    bw = belly_w if belly_w is not None else max(0.15 * (hi - lo), 1.0)
    g = np.exp(-0.5 * ((t - bt) / bw) ** 2)
    g = g - (g[0] + (g[-1] - g[0]) * (t - lo) / (hi - lo))
    peak = g[np.argmax(np.abs(g))]
    return lin + belly_bp * g / peak if abs(peak) > 1e-12 else lin


def carry_roll(curve: Curve, notional, T, freq, horizon):
    """Receive-fixed swap struck at par today. Carry = accrual differential over `horizon`;
    roll-down = revaluation after `horizon` with the curve unchanged as a function of remaining maturity."""
    K = curve.par_rate(T, freq)
    h = horizon
    fl = (curve.df_at(0.0) / curve.df_at(h) - 1.0) / h if h > 0 else 0.0
    carry = notional * (K - fl) * h
    rem = T - h
    if rem < 1.0 / freq:
        return {"K": K, "carry": carry, "roll": np.nan, "total": np.nan}
    pv_h = notional * (K - curve.par_rate(rem, freq)) * curve.annuity(rem, freq)
    return {"K": K, "carry": carry, "roll": pv_h, "total": carry + pv_h}


def validate(curve: Curve):
    """Repricing and consistency checks; returns list of dicts."""
    rows = []

    def add(name, value, tol, sev="error"):
        rows.append({"test": name, "value": float(value), "tol": float(tol), "pass": bool(abs(value) <= tol), "severity": sev})

    err = 0.0
    for i in curve.instruments:
        if i.kind == "dep":
            err = max(err, abs(1.0 / curve.df_at(i.tenor) - 1.0 - i.quote * i.tenor))
        else:
            err = max(err, abs(curve.par_rate(i.tenor, curve.freq) - i.quote))
    add("reprice", err * 1e4, 1e-6)
    add("df0", curve.df_at(0.0) - 1.0, 1e-14)
    t = np.arange(0.25, curve.tmax + 1e-9, 0.25)
    add("df_pos", min(0.0, float(np.min(curve.df_at(t)))), 0.0)
    f = np.array([curve.forward(a - 0.25, a, "cc") for a in t])
    add("fwd_chain", float(np.max(np.abs(np.exp(-np.cumsum(f) * 0.25) - curve.df_at(t)))), 1e-12)
    add("fwd_neg", min(0.0, float(np.min(f))) * 1e4, 1e-9, "info")
    rt = max(abs(convert_rate(0.037, 7.3, a, b) - convert_rate(convert_rate(0.037, 7.3, a, "cc"), 7.3, "cc", b))
             for a in CONVENTIONS for b in CONVENTIONS)
    add("conv_rt", rt, 1e-12)
    T10 = min(10.0, curve.tmax)
    add("par_pv", swap_pv(curve, 1.0, curve.par_rate(T10, curve.freq), T10, curve.freq), 1e-12)
    return rows

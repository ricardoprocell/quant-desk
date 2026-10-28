"""Quant Desk - options engine: Black-Scholes-Merton, CRR lattice, Greeks, strategies, sensitivity, regime."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq

N = norm.cdf
n = norm.pdf


# ------------------------------------------------------------------------------- BSM
def _d(S, K, r, q, sig, T):
    sq = sig * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sig ** 2) * T) / sq
    return d1, d1 - sq


def bsm(S, K, r, q, sig, T, cp="call"):
    """Price. cp: 'call'|'put'. Handles T->0 (intrinsic)."""
    S, K, sig, T = map(lambda x: np.asarray(x, float), (S, K, sig, T))
    s = 1 if cp == "call" else -1
    with np.errstate(all="ignore"):
        d1, d2 = _d(S, K, r, q, sig, T)
        px = s * (S * np.exp(-q * T) * N(s * d1) - K * np.exp(-r * T) * N(s * d2))
    intrinsic = np.maximum(s * (S - K), 0.0)
    out = np.where(T <= 1e-10, intrinsic, px)
    return float(out) if out.ndim == 0 else out


def greeks(S, K, r, q, sig, T, cp="call"):
    """Analytic Greeks. theta per day, vega & rho per 1 vol-pt / 1 pct-pt, plus vanna, volga, charm (per day)."""
    s = 1 if cp == "call" else -1
    d1, d2 = _d(S, K, r, q, sig, T)
    eq, er, sq = np.exp(-q * T), np.exp(-r * T), np.sqrt(T)
    delta = s * eq * N(s * d1)
    gamma = eq * n(d1) / (S * sig * sq)
    vega = S * eq * n(d1) * sq
    theta = (-S * eq * n(d1) * sig / (2 * sq) - s * r * K * er * N(s * d2) + s * q * S * eq * N(s * d1))
    rho = s * K * T * er * N(s * d2)
    vanna = -eq * n(d1) * d2 / sig
    volga = vega * d1 * d2 / sig
    charm = s * q * eq * N(s * d1) - eq * n(d1) * (2 * (r - q) * T - d2 * sig * sq) / (2 * T * sig * sq)
    return {"delta": delta, "gamma": gamma, "vega": vega / 100, "theta": theta / 365, "rho": rho / 100,
            "vanna": vanna / 100, "volga": volga / 1e4, "charm": charm / 365}


def implied_vol(price, S, K, r, q, T, cp="call"):
    s = 1 if cp == "call" else -1
    lo = max(s * (S * np.exp(-q * T) - K * np.exp(-r * T)), 0.0)
    if price <= lo + 1e-12 or T <= 0:
        return np.nan
    try:
        return brentq(lambda v: bsm(S, K, r, q, v, T, cp) - price, 1e-4, 6.0, xtol=1e-10)
    except ValueError:
        return np.nan


# ------------------------------------------------------------------------------ CRR
def crr(S, K, r, q, sig, T, cp="call", steps=10, american=False):
    """Cox-Ross-Rubinstein lattice. Returns dict with price, node arrays (list per layer), delta/gamma/theta at nodes."""
    dt = T / steps
    u = np.exp(sig * np.sqrt(dt))
    d = 1 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)
    if not (0 < p < 1):
        raise ValueError("Tree is arbitrageable: increase steps or volatility (p outside (0,1)).")
    disc = np.exp(-r * dt)
    s = 1 if cp == "call" else -1
    spot = [S * u ** (np.arange(i, -1, -1)) * d ** (np.arange(0, i + 1)) for i in range(steps + 1)]
    val = [None] * (steps + 1)
    exer = [None] * (steps + 1)
    val[steps] = np.maximum(s * (spot[steps] - K), 0.0)
    exer[steps] = np.zeros(steps + 1, bool)
    for i in range(steps - 1, -1, -1):
        cont = disc * (p * val[i + 1][:-1] + (1 - p) * val[i + 1][1:])
        if american:
            iv = np.maximum(s * (spot[i] - K), 0.0)
            exer[i] = iv > cont + 1e-12
            val[i] = np.maximum(cont, iv)
        else:
            exer[i] = np.zeros(i + 1, bool)
            val[i] = cont
    delta = [None] * steps
    for i in range(steps):
        delta[i] = (val[i + 1][:-1] - val[i + 1][1:]) / (spot[i + 1][:-1] - spot[i + 1][1:])
    gamma = [None] * max(steps - 1, 0)
    for i in range(steps - 1):
        up, dn = delta[i + 1][:-1], delta[i + 1][1:]
        gamma[i] = (up - dn) / (0.5 * (spot[i + 2][:-2] - spot[i + 2][2:]))
    out = {"price": float(val[0][0]), "spot": spot, "value": val, "delta": delta, "gamma": gamma, "exercise": exer,
           "u": u, "d": d, "p": p, "dt": dt}
    if steps >= 2:
        out["delta0"] = float(delta[0][0])
        out["gamma0"] = float(gamma[0][0])
        out["theta0"] = float((val[2][1] - val[0][0]) / (2 * dt) / 365)   # centre node of layer 2 has S=S0
    else:
        out["delta0"], out["gamma0"], out["theta0"] = float(delta[0][0]), np.nan, np.nan
    return out


def crr_convergence(S, K, r, q, sig, T, cp="call", american=False, steps_list=range(1, 11)):
    bs = bsm(S, K, r, q, sig, T, cp)
    rows = []
    for k in steps_list:
        try:
            t = crr(S, K, r, q, sig, T, cp, k, american)
            rows.append({"steps": k, "price": t["price"], "delta": t["delta0"], "gamma": t["gamma0"], "err": t["price"] - bs})
        except ValueError:
            rows.append({"steps": k, "price": np.nan, "delta": np.nan, "gamma": np.nan, "err": np.nan})
    return pd.DataFrame(rows), bs


# --------------------------------------------------------------------------- positions
@dataclass
class Leg:
    cp: str            # call | put | stock
    K: float
    qty: float         # signed contracts (+ long / - short)
    T: float
    sig: float
    mult: float = 100.0
    premium: float | None = None   # per unit; None -> BSM fair value at inception


def leg_price(leg, S, r, q, T=None, sig=None):
    T = leg.T if T is None else T
    sig = leg.sig if sig is None else sig
    if leg.cp == "stock":
        return S
    return bsm(S, leg.K, r, q, sig, T, leg.cp)


def position_value(legs, S, r, q, dT=0.0, dsig=0.0):
    """Mark-to-model value of the whole position (cash terms)."""
    tot = 0.0
    for L in legs:
        T = max(L.T - dT, 0.0)
        tot += L.qty * L.mult * leg_price(L, S, r, q, T, max(L.sig + dsig, 1e-4))
    return tot


def entry_cost(legs, S0, r, q):
    return sum(L.qty * L.mult * (L.premium if L.premium is not None else leg_price(L, S0, r, q)) for L in legs)


def position_greeks(legs, S, r, q):
    keys = ["delta", "gamma", "vega", "theta", "rho", "vanna", "volga", "charm"]
    tot = dict.fromkeys(keys, 0.0)
    for L in legs:
        if L.cp == "stock":
            tot["delta"] += L.qty * L.mult
            continue
        g = greeks(S, L.K, r, q, L.sig, L.T, L.cp)
        for k in keys:
            tot[k] += L.qty * L.mult * float(g[k])
    return tot


def payoff_at_expiry(legs, Sgrid, S0, r, q):
    """P&L at the FIRST expiry. Legs that expire later are still alive and valued with BSM on their remaining life."""
    Sg = np.asarray(Sgrid, float)
    opt = [L.T for L in legs if L.cp != "stock"]
    Tm = min(opt) if opt else 0.0
    tot = np.zeros_like(Sg)
    for L in legs:
        if L.cp == "stock":
            pay = Sg
        elif L.T - Tm < 1e-9:
            pay = np.maximum(Sg - L.K, 0) if L.cp == "call" else np.maximum(L.K - Sg, 0)
        else:
            pay = O_bsm_grid(Sg, L, r, q, L.T - Tm)
        tot += L.qty * L.mult * pay
    return tot - entry_cost(legs, S0, r, q)


def O_bsm_grid(Sg, L, r, q, T):
    return np.array([bsm(max(s, 1e-9), L.K, r, q, L.sig, T, L.cp) for s in Sg])


def pnl_curve(legs, Sgrid, S0, r, q, dT=0.0, dsig=0.0):
    c0 = entry_cost(legs, S0, r, q)
    return np.array([position_value(legs, s, r, q, dT, dsig) for s in Sgrid]) - c0


def strategy_stats(legs, S0, r, q, span=0.6):
    """Max profit / loss / breakevens at expiry over a +-span spot range (unbounded flagged)."""
    Sg = np.linspace(0.0, S0 * (1 + span) * 1.5, 4001)
    pl = payoff_at_expiry(legs, Sg, S0, r, q)
    be = Sg[:-1][np.sign(pl[:-1]) * np.sign(pl[1:]) < 0]
    slope_hi = (pl[-1] - pl[-2]) / (Sg[-1] - Sg[-2])
    thr = 0.05 * sum(abs(L.qty) * L.mult for L in legs)       # tail slope above 5% of gross size = unbounded
    return {"cost": entry_cost(legs, S0, r, q),
            "max_profit": np.inf if slope_hi > thr else float(pl.max()),
            "max_loss": -np.inf if slope_hi < -thr else float(pl.min()),
            "breakevens": [float(b) for b in be]}


def attribution(legs, S0, S1, r, q, dT, dsig):
    """Taylor P&L split using Greeks at S0 (delta, gamma, vega, theta) + residual vs full revaluation."""
    g = position_greeks(legs, S0, r, q)
    dS = S1 - S0
    parts = {"delta": g["delta"] * dS, "gamma": 0.5 * g["gamma"] * dS ** 2, "vega": g["vega"] * dsig * 100,
             "theta": g["theta"] * dT * 365}
    full = position_value(legs, S1, r, q, dT, dsig) - position_value(legs, S0, r, q)
    parts["residual"] = full - sum(parts.values())
    parts["total"] = full
    return parts


def breakeven_move(legs, S0, r, q):
    """Daily 1-sigma move (in S) that gamma P&L needs to offset theta: |theta| = 0.5 Gamma dS^2."""
    g = position_greeks(legs, S0, r, q)
    if g["gamma"] <= 1e-12 or g["theta"] >= 0:
        return np.nan
    return float(np.sqrt(2 * -g["theta"] / g["gamma"]))


# ------------------------------------------------------------------------ sensitivity
def greek_surface(legs, name, S0, r, q, Sgrid, Tgrid):
    """Greek of the position as function of spot and time-to-go (T shifted from now)."""
    M = np.zeros((len(Tgrid), len(Sgrid)))
    for i, dT in enumerate(Tgrid):
        sh = [Leg(L.cp, L.K, L.qty, max(L.T - dT, 1e-4), L.sig, L.mult, L.premium) for L in legs]
        for j, s in enumerate(Sgrid):
            M[i, j] = position_greeks(sh, s, r, q)[name]
    return M


def pnl_heatmap(legs, S0, r, q, spot_moves, vol_moves, dT=0.0):
    """Rows = vol shift (pts), columns = spot move (%). Full revaluation."""
    c0 = position_value(legs, S0, r, q)
    return np.array([[position_value(legs, S0 * (1 + m), r, q, dT, dv) - c0 for m in spot_moves] for dv in vol_moves])


def ladder(legs, S0, r, q, moves):
    c0 = position_value(legs, S0, r, q)
    rows = []
    for m in moves:
        S1 = S0 * (1 + m)
        g = position_greeks(legs, S1, r, q)
        rows.append({"move": m, "S": S1, "pnl": position_value(legs, S1, r, q) - c0, "delta": g["delta"], "gamma": g["gamma"],
                     "vega": g["vega"]})
    return pd.DataFrame(rows)


def smile_from_chain(chain, S, r, q, T):
    """chain: DataFrame[strike, mid, cp] -> adds iv column."""
    c = chain.copy()
    c["iv"] = [implied_vol(m, S, k, r, q, T, cp) for m, k, cp in zip(c["mid"], c["strike"], c["cp"])]
    return c


# ----------------------------------------------------------------------------- regime
def realized_vol(prices, window=21):
    r = np.log(np.asarray(prices, float))
    r = np.diff(r)
    return float(np.std(r[-window:], ddof=1) * np.sqrt(252)) if len(r) >= window else np.nan


def detect_regime(prices, iv_atm, skew=None):
    """Classify the market from price history + ATM IV (+ optional put-call skew in vol pts).
    Returns dict: vol_state (rich/cheap/fair), trend (up/down/range), skew_state, tags."""
    p = np.asarray(prices, float)
    rv = realized_vol(p, 21)
    rv_long = realized_vol(p, min(len(p) - 1, 126))
    ratio = iv_atm / rv if rv and rv > 0 else np.nan
    vol_state = "rich" if ratio > 1.2 else "cheap" if ratio < 0.85 else "fair"
    ret60 = p[-1] / p[max(-61, -len(p))] - 1
    sma50 = p[-50:].mean() if len(p) >= 50 else p.mean()
    trend = "up" if (p[-1] > sma50 and ret60 > 0.03) else "down" if (p[-1] < sma50 and ret60 < -0.03) else "range"
    skew_state = "none"
    if skew is not None and not np.isnan(skew):
        skew_state = "steep" if skew > 0.05 else "flat" if skew < 0.01 else "normal"
    return {"rv": rv, "rv_long": rv_long, "iv": iv_atm, "iv_rv": ratio, "vol_state": vol_state, "trend": trend,
            "ret60": ret60, "skew": skew, "skew_state": skew_state}


# --------------------------------------------------------------------------- strategies
def build_strategy(name, S, T, sig, qty=1, mult=100.0, width=0.05, wing=0.10):
    """Library of defined strategies around spot S (strikes rounded to 1)."""
    k = lambda m: float(np.round(S * m))
    L = lambda cp, K, qt: Leg(cp, K, qt * qty, T, sig, mult)
    A = k(1.0)
    lo, hi = k(1 - width), k(1 + width)
    wlo, whi = k(1 - wing), k(1 + wing)
    lib = {
        "long_call": [L("call", A, 1)], "long_put": [L("put", A, 1)],
        "covered_call": [L("stock", 0, 1), L("call", hi, -1)],
        "protective_put": [L("stock", 0, 1), L("put", lo, 1)],
        "collar": [L("stock", 0, 1), L("put", lo, 1), L("call", hi, -1)],
        "bull_call_spread": [L("call", A, 1), L("call", hi, -1)],
        "bear_put_spread": [L("put", A, 1), L("put", lo, -1)],
        "long_straddle": [L("call", A, 1), L("put", A, 1)],
        "short_straddle": [L("call", A, -1), L("put", A, -1)],
        "long_strangle": [L("call", hi, 1), L("put", lo, 1)],
        "short_strangle": [L("call", hi, -1), L("put", lo, -1)],
        "iron_condor": [L("put", wlo, 1), L("put", lo, -1), L("call", hi, -1), L("call", whi, 1)],
        "butterfly": [L("call", lo, 1), L("call", A, -2), L("call", hi, 1)],
        "risk_reversal": [L("call", hi, 1), L("put", lo, -1)],
        "put_ratio_spread": [L("put", A, 1), L("put", wlo, -2)],
        "calendar": [Leg("call", A, -1 * qty, T, sig, mult), Leg("call", A, 1 * qty, T * 2, sig, mult)],
    }
    return lib[name]


STRATEGY_VIEW = {  # name: (view, vol_exposure)
    "long_call": ("bullish", "long vol"), "long_put": ("bearish", "long vol"),
    "covered_call": ("mildly bullish / income", "short vol"), "protective_put": ("long, hedged", "long vol"),
    "collar": ("long, hedged cheaply", "neutral vol"), "bull_call_spread": ("moderately bullish", "~neutral vol"),
    "bear_put_spread": ("moderately bearish", "~neutral vol"), "long_straddle": ("big move either way", "long vol"),
    "short_straddle": ("pinned near spot", "short vol"), "long_strangle": ("big move either way, cheaper", "long vol"),
    "short_strangle": ("range-bound", "short vol"), "iron_condor": ("range-bound, capped risk", "short vol"),
    "butterfly": ("pin at a level", "short vol"), "risk_reversal": ("bullish, funded by skew", "skew"),
    "put_ratio_spread": ("mildly bearish / vol-sell skew", "short vol, tail risk"),
    "calendar": ("quiet now, move later", "long term / short front vol"),
}


def recommend(regime, top=3):
    """Rule-based ranking: maps (vol_state, trend, skew) to strategies, with plain-language rationale keys."""
    v, t, sk = regime["vol_state"], regime["trend"], regime["skew_state"]
    sc = {k: 0.0 for k in STRATEGY_VIEW}
    why = {k: [] for k in STRATEGY_VIEW}

    def add(k, w, tag):
        sc[k] += w
        why[k].append(tag)

    if v == "rich":
        for k in ("iron_condor", "short_strangle", "covered_call", "butterfly", "put_ratio_spread"):
            add(k, 2, "iv_rich")
        for k in ("long_straddle", "long_strangle", "long_call", "long_put"):
            add(k, -2, "iv_rich")
    elif v == "cheap":
        for k in ("long_straddle", "long_strangle", "long_call", "long_put", "protective_put", "calendar"):
            add(k, 2, "iv_cheap")
        for k in ("short_straddle", "short_strangle", "iron_condor"):
            add(k, -2, "iv_cheap")
    else:
        for k in ("bull_call_spread", "bear_put_spread", "collar", "butterfly"):
            add(k, 1, "iv_fair")
    if t == "up":
        for k in ("bull_call_spread", "risk_reversal", "covered_call", "long_call"):
            add(k, 2, "trend_up")
        for k in ("long_put", "bear_put_spread"):
            add(k, -2, "trend_up")
    elif t == "down":
        for k in ("bear_put_spread", "long_put", "protective_put", "collar"):
            add(k, 2, "trend_down")
        for k in ("long_call", "bull_call_spread", "risk_reversal"):
            add(k, -2, "trend_down")
    else:
        for k in ("iron_condor", "butterfly", "short_strangle", "calendar", "covered_call"):
            add(k, 1.5, "range")
        for k in ("long_straddle", "long_strangle"):
            add(k, 0.5, "range")
    if sk == "steep":
        for k in ("risk_reversal", "put_ratio_spread", "covered_call"):
            add(k, 1, "skew_steep")
        for k in ("protective_put",):
            add(k, -1, "skew_steep")
    elif sk == "flat":
        for k in ("protective_put", "collar"):
            add(k, 1, "skew_flat")
    order = sorted(sc, key=lambda k: -sc[k])[:top]
    return [{"name": k, "score": sc[k], "why": why[k], "view": STRATEGY_VIEW[k][0], "vol": STRATEGY_VIEW[k][1]} for k in order]

"""Quant Desk - forwards / futures on storable commodities (cost of carry, replication, arbitrage)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def fair_forward(S, r, T, u=0.0, y=0.0):
    """F = S e^{(r+u-y)T}; r cc risk-free, u storage cost, y convenience yield (cc, annual)."""
    return S * np.exp((r + u - y) * T)


def implied_yield(S, F, r, T, u=0.0):
    """Net convenience yield y that makes F fair (cc): y = r + u - ln(F/S)/T."""
    return r + u - np.log(F / S) / T


def implied_repo(S, F, T, u=0.0, y=0.0):
    """Financing rate implied by market F: r = ln(F/S)/T - u + y."""
    return np.log(F / S) / T - u + y


def forward_value(S, K, r, T, u=0.0, y=0.0, pos=1, qty=1.0):
    """MTM of a forward struck at K, maturity T remaining: pos*(F-K)e^{-rT}*qty. Greeks per unit."""
    F = fair_forward(S, r, T, u, y)
    pv = np.exp(-r * T)
    v = pos * qty * (F - K) * pv
    delta = pos * qty * np.exp((u - y) * T)                 # dV/dS
    # rho: d/dr[(S e^{(r+u-y)T} - K) e^{-rT}] = d/dr[S e^{(u-y)T} - K e^{-rT}] = K T e^{-rT}
    rho = pos * qty * K * T * pv
    theta = pos * qty * (-(u - y) * S * np.exp((u - y) * T) - K * r * pv)  # dV/dt (calendar), per year
    # carry sensitivities (per 1bp): V = n(S e^{(u-y)T}) - K e^{-rT}
    yield01 = -pos * qty * T * S * np.exp((u - y) * T) * 1e-4
    storage01 = pos * qty * T * S * np.exp((u - y) * T) * 1e-4
    return {"F": F, "value": v, "delta": delta, "rho_1bp": rho * 1e-4, "theta_day": theta / 365.0,
            "yield_1bp": yield01, "storage_1bp": storage01}


def payoff_curve(Sgrid, K, pos=1, qty=1.0):
    return pos * qty * (np.asarray(Sgrid) - K)


def term_structure(S, r_fn, tenors, u=0.0, y=0.0):
    """Theoretical forward curve; r_fn(T) returns cc zero rate."""
    return pd.DataFrame({"T": tenors, "r": [r_fn(t) for t in tenors],
                         "F": [fair_forward(S, r_fn(t), t, u, y) for t in tenors]})


def arbitrage(S, F_mkt, r, T, u=0.0, y=0.0, qty=1.0, tol_bp=0.0):
    """No-fee cash-and-carry test. Returns dict with signal and locked-in profit at T (and PV).
    F_mkt > F_fair -> cash & carry: borrow S, buy spot, short forward. F_mkt < F_fair -> reverse."""
    F = fair_forward(S, r, T, u, y)
    gap = F_mkt - F
    pv = gap * np.exp(-r * T) * qty
    sig = "none"
    if abs(gap) / S * 1e4 > tol_bp:
        sig = "cash_and_carry" if gap > 0 else "reverse_cash_and_carry"
    return {"F_fair": F, "F_mkt": F_mkt, "gap": gap, "gap_pct": gap / F, "profit_T": gap * qty, "profit_pv": pv, "signal": sig}


def replication_table(S0, K, r, T, u=0.0, y=0.0, steps=4, pos=1, path=None):
    """Replicating portfolio of a LONG forward (struck K, delivery T): hold n_t=e^{-(y-u)(T-t)} units, borrow K e^{-r(T-t)}.
    Rows = movements, columns = t. `path` = spot at each t (default: grows at r+u-y, i.e. spot follows carry).
    Value of replicating portfolio equals the forward value at every date. Returns (DataFrame, check_dict)."""
    ts = np.linspace(0, T, steps + 1)
    if path is None:
        path = S0 * np.exp((r + u - y) * ts)
    path = np.asarray(path, float)
    rem = T - ts
    n = np.exp((u - y) * rem)              # units of commodity held (storage cost u shrinks cash/units, yield y adds)
    loan = K * np.exp(-r * rem)            # PV of strike owed
    stock = n * path
    val = stock - loan
    F_t = path * np.exp((r + u - y) * rem)
    fwd = (F_t - K) * np.exp(-r * rem)
    rows = {
        "Spot S_t": path,
        "Units held n_t": n,
        "Commodity position  n_t·S_t": stock,
        "Loan  −K e^{−r(T−t)}": -loan,
        "Portfolio value": val,
        "Forward value (F_t−K)e^{−r(T−t)}": fwd,
    }
    # rebalancing flows between dates: buy/sell units, financed by loan change (self-financing at fixed path)
    dn = np.r_[n[0], np.diff(n)]
    rows["Δ units (trade)"] = dn
    rows["Trade cash  −Δn·S_t"] = -dn * path
    dl = np.r_[-loan[0], -np.diff(loan)]
    rows["Loan accrual/Δ"] = dl
    df = pd.DataFrame(rows, index=None).T
    df.columns = [f"t={t:.2f}" for t in ts]
    df = df * 1.0
    if pos == -1:
        df.loc[["Commodity position  n_t·S_t", "Loan  −K e^{−r(T−t)}", "Portfolio value", "Forward value (F_t−K)e^{−r(T−t)}"]] *= -1
    return df, {"max_abs_err": float(np.max(np.abs(val - fwd))), "ts": ts}


def futures_vs_forward_note():
    return "With deterministic rates futures price = forward price; daily margining only shifts cash timing."

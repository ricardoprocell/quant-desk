"""Tab 3 - options: position, lattice + BSM valuation, trading-book sensitivity, regime-aware strategies."""
from __future__ import annotations
import datetime as dt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import qd_opt as O
import qd_data as D
import qd_ui as ui

PRESETS = ["single", "long_call", "long_put", "covered_call", "protective_put", "collar", "bull_call_spread", "bear_put_spread",
           "long_straddle", "short_straddle", "long_strangle", "short_strangle", "iron_condor", "butterfly", "risk_reversal",
           "put_ratio_spread", "calendar"]
SCEN_MKT = {"rally": (0.05, 0.0, 5), "selloff": (-0.05, 3.0, 5), "crash": (-0.12, 10.0, 10), "crush": (0.0, -5.0, 5),
            "spike": (0.0, 8.0, 5), "grind": (0.02, -2.0, 15), "quiet": (0.0, 0.0, 15)}  # (spot move, vol shift in pts, days)


def _market(ticker):
    return D.fetch_underlying(ticker)


def _chain(ticker, expiry, S, T):
    return D.fetch_chain(ticker, expiry, S, T)


@st.cache_data(show_spinner=False)
def _trees(S, K, r, q, sig, T, cp, american):
    out = []
    for n in range(1, 11):
        try:
            out.append(O.crr(S, K, r, q, sig, T, cp, n, american))
        except ValueError:
            out.append(None)
    return out


def _legs_from_df(df, mult):
    legs = []
    for r in df.dropna(subset=["type", "qty", "days"]).itertuples():
        if float(r.qty) == 0:
            continue
        legs.append(O.Leg(str(r.type), float(r.strike) if r.strike == r.strike else 0.0, float(r.qty), max(float(r.days), 0.5) / 365.0,
                          max(float(r.vol), 1.0) / 100.0, mult, None if (r.premium != r.premium or r.premium is None) else float(r.premium)))
    return legs


def _df_from_legs(legs):
    return pd.DataFrame({"type": [l.cp for l in legs], "strike": [l.K for l in legs], "qty": [l.qty for l in legs],
                         "days": [round(l.T * 365) for l in legs], "vol": [round(l.sig * 100, 2) for l in legs], "premium": [l.premium for l in legs]})


def _set_preset(name, S, days, sig, qty, mult):
    T = days / 365.0
    legs = [O.Leg("call", float(np.round(S)), qty, T, sig, mult)] if name == "single" else O.build_strategy(name, S, T, sig, qty, mult)
    st.session_state["legs_df"] = _df_from_legs(legs)
    st.session_state["legs_ver"] = st.session_state.get("legs_ver", 0) + 1


def render(T, th, curve):
    ui.section(T("t3_title"), T("t3_sub"))
    # ------------------------------------------------------------ market block
    m1, m2, m3, m4, m5, m6 = st.columns([1.1, 1.2, 1, 0.9, 0.9, 1.1])
    tick = m1.text_input(T("ticker"), "SPY", key="tick").strip().upper() or "SPY"
    px, q_def, exps, meta = _market(tick)
    S0 = float(px.iloc[-1])
    if not exps:
        _t = dt.date.today()
        exps = [(_t + dt.timedelta(days=d_)).isoformat() for d_ in (30, 60, 90, 180)]
    exp = m2.selectbox(T("expiry"), exps, index=min(1, len(exps) - 1))
    Texp = max((dt.date.fromisoformat(exp) - dt.date.today()).days, 1) / 365.0
    S = m3.number_input(T("spot_px"), 0.01, 1e6, round(S0, 2), step=max(round(S0 * 0.001, 2), 0.01), format="%.2f", key=f"S_{tick}_{meta['source']}")
    r_def = float(curve.zero(max(Texp, 0.02), "cc")) if curve is not None else 0.04
    r = m4.number_input(T("rate_cc"), -5.0, 30.0, round(r_def * 100, 3), 0.05, format="%.3f", key=f"r_{round(r_def,4)}") / 100
    q = m5.number_input(T("div"), 0.0, 20.0, round(q_def * 100, 2), 0.1, format="%.2f", key=f"q_{tick}") / 100
    chain, cmeta = _chain(tick, exp, S, Texp)
    cs = O.smile_from_chain(chain, S, r, q, Texp).dropna(subset=["iv"]) if "mid" in chain else chain
    cs = cs[(cs.iv > 0.02) & (cs.iv < 3.0)]
    otm = cs[((cs.cp == "put") & (cs.strike <= S)) | ((cs.cp == "call") & (cs.strike >= S))].sort_values("strike")
    atm_iv = float(np.interp(S, otm.strike, otm.iv)) if len(otm) > 3 else O.realized_vol(px.values)
    sig = m6.number_input(T("vol_pct"), 1.0, 300.0, round(atm_iv * 100, 1), 0.5, format="%.1f", key=f"v_{tick}_{exp}_{cmeta['source']}", help=T("vol_help")) / 100
    badge = f"{meta['source']}" + (" · " + T("chain_demo") if cmeta["source"] == "DEMO" and meta["source"] == "LIVE" else "")
    st.caption(f"{T('data_src')}: **{badge}** · {meta['note']} · {T('asof')} {meta['asof']}")

    # ------------------------------------------------------------ position
    st.markdown(f"**{T('position')}**")
    p1, p2, p3, p4 = st.columns([1.6, 0.8, 0.8, 0.8])
    preset = p1.selectbox(T("preset"), PRESETS, index=1, format_func=lambda x: T("single_opt") if x == "single" else T("st_" + x))
    pq = p2.number_input(T("contracts"), 1, 1000, 1, key="pq")
    mult = p3.number_input(T("multiplier"), 1, 10000, 100, key="mult")
    if "legs_df" not in st.session_state:
        _set_preset("long_call", S, max(int(Texp * 365), 1), sig, 1, 100)
    if p4.button(T("apply"), width="stretch", type="primary"):
        _set_preset(preset, S, max(int(Texp * 365), 1), sig, pq, mult)
        st.rerun()
    ldf = st.data_editor(st.session_state["legs_df"], hide_index=True, width="stretch", num_rows="dynamic", key=f"legs{st.session_state.get('legs_ver', 0)}",
                         column_config={"type": st.column_config.SelectboxColumn(T("l_type"), options=["call", "put", "stock"], required=True),
                                        "strike": st.column_config.NumberColumn(T("strike"), format="%.2f"),
                                        "qty": st.column_config.NumberColumn(T("l_qty"), help=T("l_qty_help"), format="%.2f"),
                                        "days": st.column_config.NumberColumn(T("l_days"), min_value=1, format="%d"),
                                        "vol": st.column_config.NumberColumn(T("vol_pct"), min_value=1.0, format="%.1f"),
                                        "premium": st.column_config.NumberColumn(T("l_prem"), help=T("l_prem_help"), format="%.2f")})
    legs = _legs_from_df(ldf, mult)
    if not legs:
        ui.note(T("no_legs"), "warn")
        return
    opt_idx = [i for i, l in enumerate(legs) if l.cp != "stock"]

    tabs = st.tabs([T("v_val"), T("v_sens"), T("v_strat")])
    with tabs[0]:
        _valuation(T, th, legs, opt_idx, S, r, q)
    with tabs[1]:
        _sensitivity(T, th, legs, S, r, q, otm, px, atm_iv)
    with tabs[2]:
        _strategies(T, th, legs, S, r, q, sig, px, atm_iv, otm, Texp, mult)


# ======================================================================================= valuation
def _valuation(T, th, legs, opt_idx, S, r, q):
    if not opt_idx:
        ui.note(T("need_option"), "warn")
        return
    c1, c2, c3 = st.columns([1.4, 1, 1])
    which = c1.selectbox(T("which_leg"), opt_idx, format_func=lambda i: f"#{i+1} · {T('l_'+legs[i].cp) if ('l_'+legs[i].cp) else legs[i].cp} {legs[i].K:g} · {legs[i].T*365:.0f}d · {legs[i].qty:+g}")
    american = c2.toggle(T("american"), False, help=T("american_help"))
    L = legs[which]
    cp, K, Tn, sg = L.cp, L.K, L.T, L.sig
    bsm = O.bsm(S, K, r, q, sg, Tn, cp)
    g = O.greeks(S, K, r, q, sg, Tn, cp)
    trees = _trees(S, K, r, q, sg, Tn, cp, american)
    if any(t is None for t in trees):
        st.warning(T("tree_arb"))
        trees = [t for t in trees]
        valid = [t for t in trees if t is not None]
        if not valid:
            return
    t10 = trees[-1] if trees[-1] is not None else valid[-1]
    err = t10["price"] - bsm
    ui.kpi_strip(th, [
        {"label": T("bsm"), "value": bsm, "dec": 4, "acc": 1, "tone": "", "sub": T("per_unit")},
        {"label": T("crr10"), "value": t10["price"], "dec": 4, "sub": T("american") if american else T("european")},
        {"label": T("err"), "value": err, "dec": 4, "sub": f"{err/bsm*100:+.2f}%" if bsm > 1e-9 else "", "tone": ""},
        {"label": "Δ", "value": g["delta"], "dec": 4, "sub": "BSM"},
        {"label": "Γ", "value": g["gamma"], "dec": 5, "sub": "BSM"},
        {"label": "Vega", "value": g["vega"], "dec": 4, "sub": T("per_volpt")},
        {"label": "Θ/" + T("day"), "value": g["theta"], "dec": 4, "sub": T("per_day"), "tone": "neg" if g["theta"] < 0 else "pos"},
        {"label": "ρ", "value": g["rho"], "dec": 4, "sub": T("per_1pct")},
    ])
    ui.section(T("lattice"), T("lattice_sub"))
    labels = {k: T("lt_" + k) for k in ("play", "back", "conv", "value", "spot", "layer", "node", "exercise", "tree", "price", "error", "day")}
    bs_d = {"price": bsm, "delta": g["delta"], "gamma": g["gamma"], "theta": g["theta"]}
    tr_ok = [t if t is not None else dict(price=np.nan, spot=[[S]], value=[[np.nan]], delta=[], gamma=[], exercise=[[False]], delta0=np.nan, gamma0=np.nan, theta0=np.nan, u=np.nan, p=np.nan) for t in trees]
    ui.lattice_player(th, tr_ok, bs_d, cp, labels, height=510)
    ui.note(T("lattice_note", u=f"{t10['u']:.4f}", p=f"{t10['p']:.4f}"))

    a, b = st.columns(2, gap="large")
    Sg = np.linspace(S * 0.6, S * 1.4, 160)
    fig = go.Figure()
    s_ = 1 if cp == "call" else -1
    fig.add_trace(go.Scatter(x=Sg, y=np.maximum(s_ * (Sg - K), 0), name=T("intrinsic"), line=dict(color=th["mute"], width=1.6, dash="dash")))
    for frac, col in ((1.0, th["accent"]), (0.5, th["c"][1]), (0.1, th["c"][2])):
        fig.add_trace(go.Scatter(x=Sg, y=O.bsm(Sg, K, r, q, sg, max(Tn * frac, 1e-4), cp), name=f"T×{frac:g}", line=dict(color=col, width=3 if frac == 1 else 2)))
    fig.add_vline(x=S, line=dict(color=th["mute"], width=1, dash="dot"))
    fig.update_layout(**ui.plotly_layout(th, 320, title=dict(text=T("val_vs_spot"), font=dict(size=14)), xaxis_title=T("spot_px")))
    a.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    vs = np.linspace(max(sg * 0.4, 0.02), sg * 2.0, 100)
    fig = go.Figure(go.Scatter(x=vs * 100, y=[O.bsm(S, K, r, q, v_, Tn, cp) for v_ in vs], line=dict(color=th["accent"], width=3), name=T("bsm")))
    fig.add_vline(x=sg * 100, line=dict(color=th["mute"], width=1, dash="dot"))
    fig.update_layout(**ui.plotly_layout(th, 320, title=dict(text=T("val_vs_vol"), font=dict(size=14)), xaxis_title=T("vol_pct"), showlegend=False))
    b.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with st.expander(T("checks_title")):
        big = O.crr(S, K, r, q, sg, Tn, cp, 400, american)["price"]
        eur = O.bsm(S, K, r, q, sg, Tn, cp)
        c_, p_ = O.bsm(S, K, r, q, sg, Tn, "call"), O.bsm(S, K, r, q, sg, Tn, "put")
        par = c_ - p_ - (S * np.exp(-q * Tn) - K * np.exp(-r * Tn))
        iv_rt = O.implied_vol(eur, S, K, r, q, Tn, cp)
        rows = [(T("chk_parity"), par, 1e-10), (T("chk_crr400"), big - (bsm if not american else big), 5e-2 if not american else 1e9), (T("chk_iv"), iv_rt - sg, 1e-7)]
        st.dataframe(pd.DataFrame([{T("test"): a_, T("value"): f"{v_:.2e}", T("tol"): f"{t_:.0e}", "": "✓" if abs(v_) <= t_ else "✗"} for a_, v_, t_ in rows]), hide_index=True, width="stretch")


# ===================================================================================== sensitivity
def _sensitivity(T, th, legs, S, r, q, otm, px, atm_iv):
    g = O.position_greeks(legs, S, r, q)
    ui.kpi_strip(th, [
        {"label": T("k_delta"), "value": g["delta"], "dec": 1, "sub": T("shares_eq")},
        {"label": T("k_cashdelta"), "value": g["delta"] * S, "dec": 0, "prefix": "$", "sub": T("notional_eq")},
        {"label": T("k_gamma"), "value": g["gamma"] * S * S / 100, "dec": 0, "prefix": "$", "sub": T("per_1pct_move"), "tone": "pos" if g["gamma"] >= 0 else "neg"},
        {"label": "Vega", "value": g["vega"], "dec": 0, "prefix": "$", "sub": T("per_volpt"), "tone": "pos" if g["vega"] >= 0 else "neg"},
        {"label": "Θ/" + T("day"), "value": g["theta"], "dec": 0, "prefix": "$", "sub": T("per_day"), "tone": "pos" if g["theta"] >= 0 else "neg"},
        {"label": "ρ", "value": g["rho"], "dec": 0, "prefix": "$", "sub": T("per_1pct")},
    ])
    maxdays = max(l.T for l in legs) * 365
    hz = st.slider(T("horizon_days"), 0, int(max(min(maxdays - 1, 90), 0)), 0, 1, key="hz") if maxdays > 2 else 0
    dT = hz / 365.0
    a, b = st.columns(2, gap="large")
    with a:
        mv = np.linspace(-0.2, 0.2, 21)
        vv = np.array([-10, -7.5, -5, -2.5, 0, 2.5, 5, 7.5, 10]) / 100
        Z = O.pnl_heatmap(legs, S, r, q, mv, vv, dT)
        fig = go.Figure(go.Heatmap(z=Z, x=mv * 100, y=vv * 100, zmid=0, xgap=1, ygap=1,
                                   colorscale=[[0, th["neg"]], [0.5, th["panel2"]], [1, th["pos"]]],
                                   hovertemplate=T("hm_hover") + "<extra></extra>", colorbar=dict(thickness=8, len=0.8, tickformat="$,.0f")))
        fig.update_layout(**ui.plotly_layout(th, 380, title=dict(text=T("hm_title"), font=dict(size=14)), hovermode="closest", xaxis_title=T("spot_move"), yaxis_title=T("vol_shift"), xaxis=dict(ticksuffix="%", dtick=5), yaxis=dict(dtick=5)))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with b:
        gname = st.segmented_control(T("greek"), ["delta", "gamma", "vega", "theta"], default="delta", key="gname", format_func=lambda x: {"delta": "Δ", "gamma": "Γ", "vega": "Vega", "theta": "Θ"}[x], label_visibility="collapsed") or "delta"
        Sg = np.linspace(S * 0.75, S * 1.25, 120)
        fig = go.Figure()
        for dd, nm, col, w in ((0, T("today"), th["accent"], 3), (dT, T("plus_h", d=hz), th["c"][1], 2)):
            if dd == 0 and hz == 0 and nm != T("today"):
                continue
            if dd > 0 or nm == T("today"):
                sh = [O.Leg(l.cp, l.K, l.qty, max(l.T - dd, 1e-4), l.sig, l.mult, l.premium) for l in legs]
                fig.add_trace(go.Scatter(x=Sg, y=[O.position_greeks(sh, s_, r, q)[gname] for s_ in Sg], name=nm, line=dict(color=col, width=w), hovertemplate="%{y:,.2f}"))
        fig.add_vline(x=S, line=dict(color=th["mute"], width=1, dash="dot"))
        fig.update_layout(**ui.plotly_layout(th, 340, title=dict(text=T("gp_title"), font=dict(size=14)), xaxis_title=T("spot_px")))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    ui.section(T("attr_title"), T("attr_sub"))
    c1, c2 = st.columns([1, 2.2], gap="large")
    with c1:
        with st.container(border=True):
            dS = st.slider(T("spot_move"), -20.0, 20.0, 2.0, 0.5, key="a_dS", format="%.1f%%") / 100
            dv = st.slider(T("vol_shift"), -15.0, 15.0, 0.0, 0.5, key="a_dv")
            dd = st.slider(T("days_fwd"), 0, int(max(min(maxdays - 1, 60), 0)) or 1, min(1, int(max(maxdays - 1, 1))), 1, key="a_dd")
    at = O.attribution(legs, S, S * (1 + dS), r, q, dd / 365, dv / 100)
    with c2:
        names = ["delta", "gamma", "vega", "theta", "residual"]
        fig = go.Figure(go.Waterfall(x=[T("a_" + n) for n in names] + [T("a_total")], measure=["relative"] * 5 + ["total"],
                                     y=[at[n] for n in names] + [None], increasing=dict(marker=dict(color=th["pos"])), decreasing=dict(marker=dict(color=th["neg"])),
                                     totals=dict(marker=dict(color=th["accent"])), connector=dict(line=dict(color=th["grid"])),
                                     hovertemplate="%{x}: $%{y:,.0f}<extra></extra>"))
        fig.update_layout(**ui.plotly_layout(th, 320, showlegend=False, hovermode="closest", yaxis_title="P&L $"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    be = O.breakeven_move(legs, S, r, q)
    if not np.isnan(be):
        ui.note(T("be_note", m=f"{be:.2f}", p=f"{be/S*100:.2f}", v=f"{be/S*np.sqrt(252)*100:.1f}"))
    else:
        ui.note(T("be_short"), "warn")

    c3, c4 = st.columns(2, gap="large")
    with c3:
        st.markdown(f"**{T('ladder')}**")
        lad = O.ladder(legs, S, r, q, [-0.10, -0.05, -0.025, 0, 0.025, 0.05, 0.10])
        lad.columns = [T("spot_move"), T("spot_px"), "P&L $", "Δ", "Γ", "Vega"]
        st.dataframe(lad.style.format({T("spot_move"): "{:+.1%}", T("spot_px"): "{:,.2f}", "P&L $": "{:+,.0f}", "Δ": "{:,.1f}", "Γ": "{:,.2f}", "Vega": "{:,.0f}"})
                     .map(lambda v_, m_=(abs(lad["P&L $"]).max() or 1.0): f"background-color: rgba({'143,196,154' if v_ >= 0 else '224,128,111'},{min(abs(v_) / m_, 1.0) * 0.45:.2f})", subset=["P&L $"]), hide_index=True, width="stretch")
    with c4:
        if len(otm) > 3:
            fig = go.Figure(go.Scatter(x=otm.strike, y=otm.iv * 100, mode="lines+markers", line=dict(color=th["c"][1], width=2.6, shape="spline"), marker=dict(size=6), name="IV"))
            fig.add_vline(x=S, line=dict(color=th["mute"], width=1, dash="dot"))
            sk = float(np.interp(S * 0.9, otm.strike, otm.iv) - np.interp(S * 1.1, otm.strike, otm.iv)) * 100
            fig.update_layout(**ui.plotly_layout(th, 300, title=dict(text=T("smile_title", sk=f"{sk:+.1f}"), font=dict(size=14)), xaxis_title=T("strike"), yaxis_title=T("vol_pct"), showlegend=False))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with st.expander(T("g2_title")):
        g2 = pd.DataFrame({T("greek"): ["Vanna", "Volga", "Charm/" + T("day")], T("value"): [g["vanna"], g["volga"], g["charm"]]})
        st.dataframe(g2.style.format({T("value"): "{:,.4f}"}), hide_index=True, width="stretch")
        st.caption(T("g2_note"))
        sname = st.selectbox(T("surf"), ["gamma", "vega", "delta", "theta"], key="surf")
        Sg = np.linspace(S * 0.85, S * 1.15, 31)
        Tg = np.linspace(0, max(maxdays - 1, 1), 24)
        Mz = O.greek_surface(legs, sname, S, r, q, Sg, Tg / 365)
        fig = go.Figure(go.Heatmap(z=Mz, x=np.round(Sg, 1), y=np.round(Tg), zmid=0, colorscale=[[0, th["neg"]], [0.5, th["panel2"]], [1, th["pos"]]], colorbar=dict(thickness=8)))
        fig.update_layout(**ui.plotly_layout(th, 320, hovermode="closest", xaxis_title=T("spot_px"), yaxis_title=T("days_fwd")))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


# ======================================================================================= strategies
def _strategies(T, th, legs, S, r, q, sig, px, atm_iv, otm, Texp, mult):
    sk = float(np.interp(S * 0.9, otm.strike, otm.iv) - np.interp(S * 1.1, otm.strike, otm.iv)) if len(otm) > 3 else np.nan
    rg = O.detect_regime(px.values, atm_iv, sk)
    ui.section(T("regime"), T("regime_sub"))
    ui.kpi_strip(th, [
        {"label": T("iv_atm"), "value": rg["iv"] * 100, "dec": 1, "suffix": "%", "sub": T("vs_" + rg["vol_state"])},
        {"label": T("rv21"), "value": rg["rv"] * 100, "dec": 1, "suffix": "%", "sub": T("rv_sub")},
        {"label": "IV / RV", "value": rg["iv_rv"], "dec": 2, "sub": T("vol_" + rg["vol_state"]), "tone": "neg" if rg["vol_state"] == "rich" else "pos" if rg["vol_state"] == "cheap" else ""},
        {"label": T("ret60"), "value": rg["ret60"] * 100, "dec": 1, "suffix": "%", "sub": T("tr_" + rg["trend"]), "tone": "pos" if rg["trend"] == "up" else "neg" if rg["trend"] == "down" else ""},
        {"label": T("skew90_110"), "value": None if np.isnan(sk) else sk * 100, "dec": 1, "suffix": " pt", "sub": T("sk_" + rg["skew_state"])},
    ])
    ui.note(T("regime_read", v=T("vol_" + rg["vol_state"]), t=T("tr_" + rg["trend"])))
    recs = O.recommend(rg, 3)
    cols = st.columns(3, gap="medium")
    for i, (c, rc) in enumerate(zip(cols, recs)):
        with c:
            pills = "".join(f'<span class="qd-pill">{T("why_" + w)}</span>' for w in dict.fromkeys(rc["why"]))
            st.markdown(f'<div class="qd-reco"><h4>{i+1}. {T("st_" + rc["name"])}</h4><p>{T("view_" + rc["name"])}</p><p>{T("vx_" + rc["name"])}</p>{pills}</div>', unsafe_allow_html=True)
            if st.button(T("load_strategy"), key=f"load{i}", width="stretch"):
                _set_preset(rc["name"], S, max(int(Texp * 365), 1), sig, 1, mult)
                st.rerun()

    ui.section(T("breakdown"), T("breakdown_sub"))
    stt = O.strategy_stats(legs, S, r, q)
    Sg = np.linspace(S * 0.7, S * 1.3, 241)
    tot_T = O.payoff_at_expiry(legs, Sg, S, r, q)
    first = min(l.T for l in legs if l.cp != "stock") if any(l.cp != "stock" for l in legs) else 0.0
    mid = O.pnl_curve(legs, Sg, S, r, q, dT=first * 0.5)
    now = O.pnl_curve(legs, Sg, S, r, q, dT=0.0)
    # risk-neutral probability of profit at the shortest expiry
    Tm = min(l.T for l in legs)
    mu, vol = (r - q - 0.5 * sig ** 2) * Tm, sig * np.sqrt(Tm)
    z = (np.log(Sg / S) - mu) / vol
    w = np.exp(-0.5 * z ** 2) / (Sg * vol * np.sqrt(2 * np.pi))
    w = w / w.sum()
    pop = float(w[tot_T > 0].sum())
    fmt_ = lambda x: "∞" if np.isinf(x) else f"${x:,.0f}"
    ui.kpi_strip(th, [
        {"label": T("net_cost"), "value": stt["cost"], "dec": 0, "prefix": "$", "sub": T("debit") if stt["cost"] > 0 else T("credit")},
        {"label": T("max_profit"), "value": None if np.isinf(stt["max_profit"]) else stt["max_profit"], "dec": 0, "prefix": "$", "sub": "∞" if np.isinf(stt["max_profit"]) else "", "tone": "pos"},
        {"label": T("max_loss"), "value": None if np.isinf(stt["max_loss"]) else stt["max_loss"], "dec": 0, "prefix": "$", "sub": T("unbounded") if np.isinf(stt["max_loss"]) else "", "tone": "neg"},
        {"label": T("breakevens"), "value": None, "sub": " · ".join(f"{b:,.1f}" for b in stt["breakevens"]) or "—"},
        {"label": T("pop"), "value": pop * 100, "dec": 0, "suffix": "%", "sub": T("pop_sub")},
    ])
    fig = go.Figure()
    for i, l in enumerate(legs):
        pay = (Sg if l.cp == "stock" else np.maximum(Sg - l.K, 0) if l.cp == "call" else np.maximum(l.K - Sg, 0)) if (l.cp == "stock" or l.T - first < 1e-9) \
            else O.O_bsm_grid(Sg, l, r, q, l.T - first)
        prem = l.premium if l.premium is not None else O.leg_price(l, S, r, q)
        fig.add_trace(go.Scatter(x=Sg, y=l.qty * l.mult * (pay - prem), name=f"#{i+1} {T('l_'+l.cp)} {l.K:g}", line=dict(color=th["c"][i % 5], width=1.3, dash="dot"), opacity=0.8, hovertemplate="$%{y:,.0f}"))
    fig.add_trace(go.Scatter(x=Sg, y=now, name=T("pnl_now"), line=dict(color=th["c"][3], width=2.2), hovertemplate="$%{y:,.0f}"))
    fig.add_trace(go.Scatter(x=Sg, y=mid, name=T("pnl_mid"), line=dict(color=th["c"][1], width=2.2), hovertemplate="$%{y:,.0f}"))
    fig.add_trace(go.Scatter(x=Sg, y=tot_T, name=T("pnl_exp"), line=dict(color=th["accent"], width=3.6), hovertemplate="$%{y:,.0f}"))
    fig.add_hline(y=0, line=dict(color=th["grid"], width=1))
    fig.add_vline(x=S, line=dict(color=th["mute"], width=1, dash="dot"))
    for b in stt["breakevens"]:
        fig.add_vline(x=b, line=dict(color=th["warn"], width=1, dash="dash"))
    fig.update_layout(**ui.plotly_layout(th, 430, xaxis_title=T("spot_at"), yaxis_title="P&L $"))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    rows = []
    for i, l in enumerate(legs):
        prem = l.premium if l.premium is not None else O.leg_price(l, S, r, q)
        gg = O.position_greeks([l], S, r, q)
        rows.append({"#": i + 1, T("l_type"): T("l_" + l.cp), T("strike"): l.K, T("l_qty"): l.qty, T("prem_cash"): -l.qty * l.mult * prem,
                     "Δ": gg["delta"], "Γ": gg["gamma"], "Vega": gg["vega"], "Θ": gg["theta"]})
    bt = pd.DataFrame(rows)
    st.dataframe(bt.style.format({T("strike"): "{:,.2f}", T("l_qty"): "{:+g}", T("prem_cash"): "{:+,.0f}", "Δ": "{:,.1f}", "Γ": "{:,.2f}", "Vega": "{:,.0f}", "Θ": "{:,.0f}"}), hide_index=True, width="stretch")

    ui.section(T("scen_mkt"), T("scen_mkt_sub"))
    base = O.position_value(legs, S, r, q)
    keys = list(SCEN_MKT)
    pl = [O.position_value(legs, S * (1 + a), r, q, d / 365.0, dv / 100) - base for a, dv, d in SCEN_MKT.values()]
    fig = go.Figure(go.Bar(x=[T("ms_" + k) for k in keys], y=pl, marker=dict(color=[th["pos"] if v >= 0 else th["neg"] for v in pl], cornerradius=4),
                           customdata=[[a * 100, dv, d] for a, dv, d in SCEN_MKT.values()],
                           hovertemplate="%{x}<br>S %{customdata[0]:+.0f}% · σ %{customdata[1]:+.0f}pt · %{customdata[2]}d<br>$%{y:,.0f}<extra></extra>"))
    fig.update_layout(**ui.plotly_layout(th, 300, showlegend=False, hovermode="closest", yaxis_title="P&L $"))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

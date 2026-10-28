"""Tab 2 - commodity forwards / futures: pricing, arbitrage radar, replication."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import qd_fwd as F
import qd_data as D
import qd_ui as ui


def _fetch(key):
    return D.fetch_commodity(key)


def _arb_table(T, pos_int, S, r, u, y, sig_, F_mkt, Tm, qty):
    n0 = np.exp((u - y) * Tm)
    s = 1 if sig_ == "cash_and_carry" else -1
    F_fair = F.fair_forward(S, r, Tm, u, y)
    rows = {
        T("a_spot"): [-s * n0 * S * qty, 0.0],
        T("a_fin"): [s * n0 * S * qty, -s * n0 * S * np.exp(r * Tm) * qty],
        T("a_fwd"): [0.0, s * F_mkt * qty],
    }
    df = pd.DataFrame(rows, index=["t=0", f"t=T ({Tm:.2f}y)"]).T
    df.loc[T("a_net")] = df.fillna(0).sum()
    return df, s * (F_mkt - F_fair) * qty, n0


def render(T, th, curve):
    ui.section(T("t2_title"), T("t2_sub"))
    top = st.columns([1.3, 1, 1, 1, 1])
    key = top[0].segmented_control(T("commodity"), list(D.COMMODITIES), default="gold", key="comm", format_func=lambda x: T("cm_" + x)) or "gold"
    spot, fut, meta = _fetch(key)
    spec = D.COMMODITIES[key]
    mult = 100 if key == "gold" else 1000
    pos = top[1].segmented_control(T("position"), [1, -1], default=1, key="fpos", format_func=lambda x: T("long") if x == 1 else T("short")) or 1
    lots = top[2].number_input(T("lots"), 1, 1000, 1, key="lots", help=T("lots_help", m=mult, u=spec["unit"].split("/")[1]))
    u = top[3].number_input(T("storage"), 0.0, 25.0, spec["u"] * 100, 0.25, format="%.2f", help=T("storage_help")) / 100
    y = top[4].number_input(T("cy"), -10.0, 30.0, spec["y"] * 100, 0.25, format="%.2f", help=T("cy_help")) / 100
    qty = lots * mult
    S = st.number_input(T("spot_px"), 0.01, 1e6, float(round(spot, 2)), step=float(max(spot * 0.001, 0.01)), format="%.2f", key=f"S_{key}_{meta['source']}")
    rfun = (lambda t_: float(curve.zero(max(t_, 0.02), "cc"))) if curve is not None else (lambda t_: 0.04)

    # ----- radar
    fut = fut.copy()
    fut["r"] = [rfun(t_) for t_ in fut["T"]]
    fut["fair"] = [F.fair_forward(S, r_, t_, u, y) for r_, t_ in zip(fut["r"], fut["T"])]
    fut["gap"] = fut["price"] - fut["fair"]
    fut["gap_bp"] = fut["gap"] / S * 1e4
    fut["impl_y"] = [F.implied_yield(S, p, r_, t_, u) for p, r_, t_ in zip(fut["price"], fut["r"], fut["T"])]
    thr = 0.0
    fut["signal"] = np.where(fut["gap_bp"].abs() < 2, "none", np.where(fut["gap"] > 0, "cash_and_carry", "reverse_cash_and_carry"))
    ui.section(T("radar"), T("radar_sub"))
    tg = np.linspace(0, max(fut["T"].max() * 1.05, 0.5), 80)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=tg, y=[F.fair_forward(S, rfun(t_), t_, u, y) for t_ in tg], name=T("theo"), line=dict(color=th["accent"], width=3),
                             hovertemplate="%{y:,.2f}"))
    cols = [th["neg"] if s_ == "cash_and_carry" else th["warn"] if s_ != "none" else th["c"][1] for s_ in fut["signal"]]
    fig.add_trace(go.Scatter(x=fut["T"], y=fut["price"], mode="markers", name=T("obs"), marker=dict(size=12, color=cols, line=dict(color=th["bg"], width=2)),
                             text=fut["ticker"], hovertemplate="%{text}: %{y:,.2f}"))
    fig.add_trace(go.Scatter(x=[0], y=[S], mode="markers", name=T("spot"), marker=dict(size=11, symbol="diamond", color=th["text"])))
    fig.update_layout(**ui.plotly_layout(th, 340, xaxis_title=T("maturity"), yaxis_title=spec["unit"]))
    c1, c2 = st.columns([1.35, 1], gap="large")
    c1.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    fb = go.Figure(go.Bar(x=fut["ticker"].str.split(".").str[0], y=fut["gap_bp"], marker=dict(color=cols, cornerradius=4),
                          hovertemplate="%{x}: %{y:+.1f} bp of spot<extra></extra>"))
    fb.update_layout(**ui.plotly_layout(th, 340, title=dict(text=T("gap_title"), font=dict(size=14)), showlegend=False, hovermode="closest", yaxis_title="bp"))
    c2.plotly_chart(fb, width="stretch", config={"displayModeBar": False})
    show = pd.DataFrame({T("contract"): fut["ticker"].str.split(".").str[0], "T": fut["T"], T("mkt_f"): fut["price"], T("fair_f"): fut["fair"],
                         T("gap"): fut["gap"], "bp": fut["gap_bp"], T("impl_y"): fut["impl_y"] * 100, T("signal"): [T("sig_" + s_) for s_ in fut["signal"]]})
    st.dataframe(show.style.format({"T": "{:.2f}", T("mkt_f"): "{:,.2f}", T("fair_f"): "{:,.2f}", T("gap"): "{:+,.2f}", "bp": "{:+.1f}", T("impl_y"): "{:.2f}%"}),
                 hide_index=True, width="stretch")
    ui.note(T("radar_note"))

    # ----- your forward
    ui.section(T("yours"), T("yours_sub"))
    labels = list(fut["ticker"].str.split(".").str[0])
    pick = st.selectbox(T("pick_contract"), labels + [T("custom")], index=min(2, len(labels) - 1))
    if pick == T("custom"):
        cA, cB = st.columns(2)
        Tm = cA.slider(T("tenor_days"), 7, 730, 180, 1) / 365
        r_ = rfun(Tm)
        Fmk = F.fair_forward(S, r_, Tm, u, y)
        Fmk = cB.number_input(T("mkt_f"), 0.01, 1e7, float(round(Fmk, 2)), format="%.2f")
    else:
        row = fut.iloc[labels.index(pick)]
        Tm, r_, Fmk = float(row["T"]), float(row["r"]), float(row["price"])
    Ffair = F.fair_forward(S, r_, Tm, u, y)
    ks = st.segmented_control(T("strike_mode"), ["mkt", "fair", "custom"], default="mkt", key="kmode", format_func=lambda x: T("km_" + x)) or "mkt"
    K = Fmk if ks == "mkt" else Ffair if ks == "fair" else st.number_input(T("strike"), 0.01, 1e7, float(round(Ffair, 2)), format="%.2f")
    v = F.forward_value(S, K, r_, Tm, u, y, pos, qty)
    ui.kpi_strip(th, [
        {"label": T("fair_f"), "value": Ffair, "dec": 2, "sub": f"r={r_*100:.2f}% · T={Tm:.2f}y"},
        {"label": T("mtm"), "value": v["value"], "dec": 0, "prefix": "$", "tone": "pos" if v["value"] >= 0 else "neg", "sub": f"K={K:,.2f}"},
        {"label": "Δ", "value": v["delta"], "dec": 0, "sub": T("units_per_usd")},
        {"label": "Rho 1bp", "value": v["rho_1bp"], "dec": 0, "prefix": "$", "sub": T("per_bp")},
        {"label": T("yield01"), "value": v["yield_1bp"], "dec": 0, "prefix": "$", "sub": T("per_bp")},
        {"label": "Θ/" + T("day"), "value": v["theta_day"], "dec": 0, "prefix": "$", "sub": T("carry_decay")},
    ])
    Sg = np.linspace(S * 0.75, S * 1.25, 120)
    mtm = [F.forward_value(s_, K, r_, Tm, u, y, pos, qty)["value"] for s_ in Sg]
    pay = F.payoff_curve(Sg, K, pos, qty)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=Sg, y=pay, name=T("payoff_T"), line=dict(color=th["c"][2], width=2, dash="dash"), hovertemplate="$%{y:,.0f}"))
    fig.add_trace(go.Scatter(x=Sg, y=mtm, name=T("mtm_now"), line=dict(color=th["accent"], width=3), hovertemplate="$%{y:,.0f}"))
    fig.add_vline(x=S, line=dict(color=th["mute"], width=1, dash="dot"), annotation_text=T("spot"), annotation_font_color=th["mute"])
    fig.add_hline(y=0, line=dict(color=th["grid"], width=1))
    fig.update_layout(**ui.plotly_layout(th, 340, xaxis_title=T("spot_at"), yaxis_title="P&L $"))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # ----- replication
    ui.section(T("repl"), T("repl_sub"))
    r1, r2 = st.columns([1, 3])
    with r1:
        steps = st.slider(T("periods"), 2, 12, 4)
        pmode = st.selectbox(T("path"), ["carry", "up", "down", "wave"], format_func=lambda x: T("p_" + x))
    ts = np.linspace(0, Tm, steps + 1)
    carry_path = S * np.exp((r_ + u - y) * ts)
    path = {"carry": carry_path, "up": S * (1 + 0.25 * ts / Tm), "down": S * (1 - 0.25 * ts / Tm),
            "wave": S * (1 + 0.12 * np.sin(2 * np.pi * ts / Tm))}[pmode]
    path[0] = S
    tab, chk = F.replication_table(S, K, r_, Tm, u, y, steps, pos, path)
    with r2:
        tab.index = [T("rp_%d" % i) for i in range(len(tab))]
        hi = {tab.index[4], tab.index[5]}
        sty = tab.style.format("{:,.2f}").apply(lambda s_: ["font-weight:700" if s_.name in hi else "" for _ in s_], axis=1)
        st.dataframe(sty, width="stretch", height=min(35 * (len(tab) + 1) + 3, 400))
        ui.note(T("repl_note", err=f"{chk['max_abs_err']:.1e}"), "pos" if chk["max_abs_err"] < 1e-6 else "neg")

    # ----- arbitrage trade
    ui.section(T("arb"), T("arb_sub"))
    ar = F.arbitrage(S, Fmk, r_, Tm, u, y, qty)
    if ar["signal"] == "none" or abs(ar["gap"]) / S * 1e4 < 0.01:
        ui.note(T("no_arb"))
    else:
        tbl, prof, n0 = _arb_table(T, pos, S, r_, u, y, ar["signal"], Fmk, Tm, qty)
        ui.kpi_strip(th, [
            {"label": T("signal"), "value": None, "sub": T("sig_" + ar["signal"])},
            {"label": T("locked"), "value": abs(ar["profit_T"]), "dec": 0, "prefix": "$", "tone": "pos", "sub": T("at_T")},
            {"label": T("locked_pv"), "value": abs(ar["profit_pv"]), "dec": 0, "prefix": "$", "tone": "pos", "sub": T("today")},
            {"label": T("units0"), "value": n0 * qty, "dec": 2, "sub": T("carry_costs_note")},
        ])
        st.dataframe(tbl.style.format("{:,.2f}", na_rep="—"), width="stretch")
        ui.note(T("arb_note"), "warn")

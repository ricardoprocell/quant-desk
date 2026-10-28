"""Tab 1 - IRS curve construction."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import qd_rates as R
import qd_data as D
import qd_ui as ui

SCEN = {"up50": ("parallel_up", 50, 50, 0), "dn50": ("parallel_down", -50, -50, 0),
        "steep": ("steepener", -25, 25, 0), "flat": ("flattener", 25, -25, 0), "belly": ("belly", 0, 0, 25)}


def _key(ins):
    return tuple((round(i.tenor, 6), i.kind, round(i.quote, 8), i.label) for i in ins)


def _ins(key):
    return [R.Instrument(*k[:3], label=k[3]) for k in key]


@st.cache_data(show_spinner=False)
def build_cached(key, freq, method):
    c = R.build_curve(_ins(key), freq, method)
    return c


@st.cache_data(show_spinner=False)
def risk_cached(key, freq, method, notional, fixed, T, receive, horizon):
    c = R.build_curve(_ins(key), freq, method)
    f = lambda cu: R.swap_pv(cu, notional, fixed, T, freq, receive)
    krd = R.key_rate_dv01(c, f)
    out = {"pv": f(c), "dv01": R.parallel_dv01(c, f), "krd": krd, "labels": [i.label for i in c.instruments],
           "tenors": [i.tenor for i in c.instruments]}
    t = [i.tenor for i in c.instruments]
    scen = {}
    for k, (nm, s, l, b) in SCEN.items():
        scen[k] = R.pnl_scenarios(c, f, {k: R.scenario_bumps(t, s, l, b)})[k]
    out["scen"] = scen
    cr = R.carry_roll(c, notional, T, freq, horizon)
    sgn = 1 if receive else -1
    out["carry"] = {k: (sgn * v if isinstance(v, float) else v) for k, v in cr.items()}
    return out


def _quotes_editor(T, quotes, meta):
    """Editable instrument table. Returns list[Instrument]."""
    sig = meta["source"] + meta["asof"]
    if st.session_state.get("_q_sig") != sig or st.session_state.get("_q_reset"):
        ins = D.curve_instruments(quotes)
        st.session_state["_q_df"] = pd.DataFrame({"label": [i.label for i in ins], "years": [i.tenor for i in ins],
                                                  "kind": [i.kind for i in ins], "rate": [i.quote * 100 for i in ins]})
        st.session_state["_q_sig"] = sig
        st.session_state["_q_ver"] = st.session_state.get("_q_ver", 0) + 1
        st.session_state["_q_reset"] = False
    df = st.data_editor(
        st.session_state["_q_df"], hide_index=True, width="stretch", num_rows="dynamic",
        key=f"qed{st.session_state['_q_ver']}", height=min(36 * (len(st.session_state['_q_df']) + 2), 430),
        column_config={"label": st.column_config.TextColumn(T("instr"), width="small"),
                       "years": st.column_config.NumberColumn(T("years"), min_value=0.002, max_value=60.0, format="%.3f", width="small"),
                       "kind": st.column_config.SelectboxColumn(T("kind"), options=["dep", "par"], width="small"),
                       "rate": st.column_config.NumberColumn(T("rate_pct"), min_value=-5.0, max_value=30.0, format="%.4f", width="small")})
    df = df.dropna(subset=["years", "kind", "rate"])
    return [R.Instrument(float(r.years), str(r.kind), float(r.rate) / 100, str(r.label) if r.label else f"{r.years:g}Y")
            for r in df.itertuples()]


def _read_through(T, st_, curve, krd):
    out = []
    shp = st_["shape"]
    s = st_["s2s10s"]
    out.append(("", T("rt_shape", shape=T("shape_" + shp), s=f"{s:+.0f}" if not np.isnan(s) else "n/a")))
    if not np.isnan(st_["f5y5y"]):
        d = (st_["f5y5y"] - curve.zero(10, "annual")) * 1e4
        kind = "pos" if d > 0 else "warn"
        out.append((kind, T("rt_fwd", f=f"{st_['f5y5y']*100:.2f}", z=f"{curve.zero(10,'annual')*100:.2f}", d=f"{d:+.0f}")))
    if st_["min_fwd"] < 0:
        out.append(("neg", T("rt_negfwd", f=f"{st_['min_fwd']*100:.2f}")))
    return out


def render(T, th, quotes, meta):
    ui.section(T("t1_title"), T("t1_sub"))
    left, right = st.columns([1.2, 2.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown(f"**{T('quotes')}**")
            ins_base = _quotes_editor(T, quotes, meta)
            if st.button(T("reset"), width="stretch"):
                st.session_state["_q_reset"] = True
                st.rerun()
            method = st.segmented_control(T("interp"), ["loglinear", "smooth"], default="smooth", key="interp",
                                          format_func=lambda x: T("m_" + x), label_visibility="collapsed") or "smooth"
            st.caption(T("interp_help"))
            freq = st.selectbox(T("freq"), [1, 2], index=1, format_func=lambda x: T("f_%d" % x))
            with st.expander(T("ois_paste")):
                st.caption(T("ois_help"))
                txt = st.text_area("OIS", value="", height=110, label_visibility="collapsed", placeholder="2Y 3.55\n5Y 3.70\n10Y 3.90\n30Y 4.00")
                if txt.strip():
                    try:
                        ois = D.parse_ois_text(txt)
                        st.success(T("ois_ok", n=len(ois)))
                        short = [i for i in ins_base if i.tenor < 1]
                        ins_base = short + [R.Instrument(t_, "par", r_, f"OIS {t_:g}Y") for t_, r_ in ois if t_ >= 1]
                    except Exception as e:  # noqa: BLE001
                        st.error(T("ois_err", e=str(e)))
    try:
        key = _key(ins_base)
        curve = build_cached(key, freq, method)
    except Exception as e:  # noqa: BLE001
        with right:
            st.error(T("build_err", e=str(e)))
        return None

    stt = R.curve_stats(curve)
    with right:
        ui.kpi_strip(th, [
            {"label": T("k_z2"), "value": stt["z2"] * 100, "dec": 3, "suffix": "%", "sub": T("cc")},
            {"label": T("k_z10"), "value": stt["z10"] * 100, "dec": 3, "suffix": "%", "sub": T("cc")},
            {"label": T("k_z30"), "value": stt["z30"] * 100, "dec": 3, "suffix": "%", "sub": T("cc")},
            {"label": "2s10s", "value": stt["s2s10s"], "dec": 0, "suffix": " bp", "sub": T("shape_" + stt["shape"]),
             "tone": "pos" if stt["s2s10s"] > 0 else "neg"},
            {"label": "5y5y fwd", "value": stt["f5y5y"] * 100 if not np.isnan(stt["f5y5y"]) else None, "dec": 3, "suffix": "%", "sub": T("annual")},
            {"label": T("k_fly"), "value": stt["fly_2_5_10"], "dec": 0, "suffix": " bp", "sub": "2s5s10s"},
        ])
        c1, c2, c3 = st.columns([1.2, 1, 1])
        view = c1.segmented_control(T("view"), ["rates", "df"], default="rates", key="cview", format_func=lambda x: T("v_" + x), label_visibility="collapsed") or "rates"
        conv = c2.selectbox(T("conv"), R.CONVENTIONS, index=0, format_func=lambda x: T("c_" + x), label_visibility="collapsed")
        scen = c3.selectbox(T("ghost"), ["none"] + list(SCEN), format_func=lambda x: T("ghost_none") if x == "none" else T("sc_" + x), label_visibility="collapsed")
        tt = np.linspace(0.02, curve.tmax, 400)
        fig = go.Figure()
        ghost = None
        if scen != "none":
            nm, s_, l_, b_ = SCEN[scen]
            bumps = R.scenario_bumps([i.tenor for i in curve.instruments], s_, l_, b_)
            try:
                ghost = R.shock(curve, bumps)
            except ValueError:
                ghost = None
        if view == "rates":
            z = R.df_to_rate(curve.df_at(tt), tt, conv) * 100
            fw = curve.inst_forward(tt) * 100 if conv == "cc" else R.convert_rate(curve.inst_forward(tt), tt * 0 + 1e-6, "cc", conv) * 100
            pr = np.array([curve.par_rate(x, freq) if x >= 1 / freq else np.nan for x in tt]) * 100
            fig.add_trace(go.Scatter(x=tt, y=fw, name=T("l_fwd"), line=dict(color=th["c"][2], width=1.6), hovertemplate="%{y:.3f}%"))
            fig.add_trace(go.Scatter(x=tt, y=pr, name=T("l_par"), line=dict(color=th["c"][1], width=2.2), hovertemplate="%{y:.3f}%"))
            fig.add_trace(go.Scatter(x=tt, y=z, name=T("l_zero") + f" ({T('c_'+conv)})", line=dict(color=th["accent"], width=3.2), hovertemplate="%{y:.3f}%",
                                     fill="tonexty" if False else None))
            piv = [i for i in curve.instruments]
            fig.add_trace(go.Scatter(x=[i.tenor for i in piv], y=[i.quote * 100 for i in piv], mode="markers", name=T("l_pillar"),
                                     marker=dict(size=9, color=th["bg"], line=dict(color=th["c"][1], width=2.2)), hovertemplate="%{text}: %{y:.3f}%",
                                     text=[i.label for i in piv]))
            if ghost is not None:
                gz = R.df_to_rate(ghost.df_at(tt), tt, conv) * 100
                fig.add_trace(go.Scatter(x=tt, y=gz, name=T("sc_" + scen), line=dict(color=th["c"][4], width=2, dash="dash"), hovertemplate="%{y:.3f}%"))
            yt = T("rate_pct")
        else:
            fig.add_trace(go.Scatter(x=tt, y=curve.df_at(tt), name="DF(t)", line=dict(color=th["accent"], width=3.2), fill="tozeroy",
                                     fillcolor=th["accent_a"], hovertemplate="%{y:.5f}"))
            if ghost is not None:
                fig.add_trace(go.Scatter(x=tt, y=ghost.df_at(tt), name=T("sc_" + scen), line=dict(color=th["c"][4], width=2, dash="dash")))
            yt = "DF"
        fig.update_layout(**ui.plotly_layout(th, 430, xaxis_title=T("maturity"), yaxis_title=yt))
        fig.update_xaxes(range=[0, curve.tmax])
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        for kind, txt_ in _read_through(T, stt, curve, None):
            ui.note(txt_, kind)

    # ---- risk of a swap
    ui.section(T("risk_title"), T("risk_sub"))
    a, b = st.columns([1, 2.6], gap="large")
    with a:
        with st.container(border=True):
            side = st.segmented_control(T("side"), ["rec", "pay"], default="rec", key="side", format_func=lambda x: T("side_" + x)) or "rec"
            N = st.number_input(T("notional"), 1e5, 1e10, 1e7, 1e6, format="%.0f")
            Tsw = st.slider(T("swap_T"), 1.0, float(min(30.0, curve.tmax)), float(min(10.0, curve.tmax)), 0.5)
            par = curve.par_rate(Tsw, freq) * 100
            K = st.number_input(T("fixed_rate"), -5.0, 30.0, round(par, 4), 0.01, format="%.4f", help=T("fixed_help", p=f"{par:.4f}"))
            hz = st.select_slider(T("horizon"), [1 / 12, 0.25, 0.5, 1.0], 0.25, format_func=lambda x: f"{x*12:.0f}M")
    rk = risk_cached(key, freq, method, float(N), K / 100, float(Tsw), side == "rec", float(hz))
    with b:
        cr = rk["carry"]
        ui.kpi_strip(th, [
            {"label": T("k_pv"), "value": rk["pv"], "dec": 0, "prefix": "$", "tone": "pos" if rk["pv"] >= 0 else "neg", "sub": T("mtm")},
            {"label": "DV01", "value": rk["dv01"], "dec": 0, "prefix": "$", "sub": T("per_bp")},
            {"label": T("k_carry"), "value": cr["carry"], "dec": 0, "prefix": "$", "sub": f"{hz*12:.0f}M", "tone": "pos" if cr["carry"] >= 0 else "neg"},
            {"label": T("k_roll"), "value": cr["roll"], "dec": 0, "prefix": "$", "sub": T("rolldown"), "tone": "pos" if (cr["roll"] or 0) >= 0 else "neg"},
            {"label": T("k_total"), "value": cr["total"], "dec": 0, "prefix": "$", "sub": T("carry_roll"), "tone": "pos" if (cr["total"] or 0) >= 0 else "neg"},
        ])
        g1, g2 = st.columns(2)
        krd = rk["krd"]
        fig = go.Figure(go.Bar(x=rk["labels"], y=krd, marker=dict(color=[th["pos"] if v >= 0 else th["neg"] for v in krd], cornerradius=4),
                               hovertemplate="%{x}: $%{y:,.0f}/bp<extra></extra>"))
        fig.update_layout(**ui.plotly_layout(th, 300, title=dict(text=T("krd_title"), font=dict(size=14)), showlegend=False, hovermode="closest"))
        g1.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        sc = rk["scen"]
        keys = list(SCEN)
        vals = [sc[k] for k in keys]
        fig = go.Figure(go.Bar(x=[T("sc_" + k) for k in keys], y=vals, marker=dict(color=[th["pos"] if (v or 0) >= 0 else th["neg"] for v in vals], cornerradius=4),
                               hovertemplate="%{x}: $%{y:,.0f}<extra></extra>"))
        fig.update_layout(**ui.plotly_layout(th, 300, title=dict(text=T("scen_title"), font=dict(size=14)), showlegend=False, hovermode="closest"))
        g2.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        # what-if text
        up = sc["up50"]
        ui.note(T("whatif", up=f"{up:+,.0f}", dn=f"{sc['dn50']:+,.0f}", dv=f"{rk['dv01']:,.0f}"))

    # ---- forwards matrix + calculator
    ui.section(T("fm_title"), T("fm_sub"))
    c1, c2 = st.columns([1.5, 1], gap="large")
    with c1:
        starts = [0, 1, 2, 5, 10]
        tens = [1, 2, 5, 10]
        fm = R.forward_matrix(curve, starts, tens) * 100
        fig = go.Figure(go.Heatmap(z=fm.values, x=[f"{t}Y" for t in tens], y=[f"{s}Y" if s else T("spot") for s in starts],
                                   colorscale=[[0, th["panel2"]], [1, th["accent"]]], text=np.round(fm.values, 3), texttemplate="%{text:.2f}%",
                                   hovertemplate=T("fm_hover") + "<extra></extra>", showscale=False, xgap=3, ygap=3))
        fig.update_layout(**ui.plotly_layout(th, 290, hovermode="closest", margin=dict(l=8, r=8, t=8, b=8)))
        fig.update_yaxes(autorange="reversed", title=T("fm_start"))
        fig.update_xaxes(title=T("fm_tenor"), side="bottom")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with c2:
        with st.container(border=True):
            st.markdown(f"**{T('calc_title')}**")
            tq = st.number_input(T("calc_t"), 0.05, float(curve.tmax), min(5.0, float(curve.tmax)), 0.25, key="calc_t")
            mode = st.segmented_control(T("calc_mode"), ["curve", "df", "rate"], default="curve", key="calc_mode", format_func=lambda x: T("cm_" + x), label_visibility="collapsed") or "curve"
            dfc = float(curve.df_at(tq))
            if mode == "curve":
                dfv = dfc
            elif mode == "df":
                dfv = st.number_input("DF", 0.0001, 1.5, round(dfc, 6), 0.001, format="%.6f")
            else:
                cv_ = st.selectbox(T("conv"), R.CONVENTIONS, format_func=lambda x: T("c_" + x), key="calc_cv")
                rv = st.number_input(T("rate_pct"), -5.0, 30.0, round(R.df_to_rate(dfc, tq, cv_) * 100, 4), 0.01, format="%.4f")
                dfv = float(R.rate_to_df(rv / 100, tq, cv_))
            rows = {T("c_" + c): R.df_to_rate(dfv, tq, c) * 100 for c in R.CONVENTIONS}
            rows = pd.DataFrame({T("conv"): list(rows), "%": [f"{v:.5f}" for v in rows.values()]})
            st.markdown(f"DF({tq:g}) = **{dfv:.6f}**")
            st.dataframe(rows, hide_index=True, width="stretch")

    with st.expander(T("table_title")):
        times = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30])
        times = times[times <= curve.tmax + 1e-9]
        tb = R.curve_table(curve, times)
        tb.columns = ["t", "DF", T("l_par"), "cc", T("c_annual"), T("c_semi"), T("c_quarterly"), T("c_simple"), "fwd 1Y", T("l_fwd")]
        pct = [c for c in tb.columns if c not in ("t", "DF")]
        tb[pct] = tb[pct] * 100
        st.dataframe(tb.style.format({"t": "{:g}", "DF": "{:.6f}", **{c: "{:.4f}" for c in pct}}), hide_index=True, width="stretch")
    with st.expander(T("checks_title")):
        vr = pd.DataFrame(R.validate(curve))
        vr["status"] = np.where(vr["pass"], "✓", np.where(vr["severity"] == "info", "i", "✗"))
        vr["test"] = [T("vt_" + x) for x in vr["test"]]
        st.dataframe(vr[["status", "test", "value", "tol"]], hide_index=True, width="stretch")
        if curve.fallback:
            st.warning(T("fallback"))
    return curve

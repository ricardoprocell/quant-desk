"""Quant Desk - Streamlit entry point."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import streamlit as st

st.set_page_config(page_title="Quant Desk", page_icon="◢", layout="wide", initial_sidebar_state="collapsed")

import qd_ui as ui
import qd_data as D
from qd_i18n import tr
import tab_curve, tab_fwd, tab_opt


def _curve_quotes():
    q, meta, _ = D.fetch_curve()
    return q, meta


def main():
    with st.sidebar:
        lang = st.segmented_control("Language / Idioma", ["en", "es"], default="en", key="lang", format_func=lambda x: {"en": "English", "es": "Español"}[x]) or "en"
        T = lambda k, **kw: tr(k, lang, **kw)
        if st.button(T("refresh"), width="stretch"):
            st.cache_data.clear()
            D.clear_cache()
            st.rerun()
        st.caption(T("about"))
    T = lambda k, **kw: tr(k, lang, **kw)
    th = ui.theme()
    ui.inject_css(th)
    quotes, meta = _curve_quotes()
    ui.hero(th, T("app_title"), T("app_sub"), meta["source"], (T("demo_warn") + " " + meta["note"]) if meta["source"] == "DEMO" else f"{meta['note']} · {meta['asof']}")
    t1, t2, t3 = st.tabs([T("tab1"), T("tab2"), T("tab3")])
    with t1:
        curve = tab_curve.render(T, th, quotes, meta)
    with t2:
        tab_fwd.render(T, th, curve)
    with t3:
        tab_opt.render(T, th, curve)


main()

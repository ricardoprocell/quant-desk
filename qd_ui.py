"""Quant Desk v2 - design system: black organic tokens, static atmosphere + living elements, spring KPI component, lattice player."""
from __future__ import annotations
import base64, hashlib, json, math
import numpy as np
import streamlit as st
from qd_motion import core_js

# Black, organic. Categorical slots validated on the dark surface (lightness band, chroma, CVD, contrast): moss, slate, clay, plum, ochre.
DARK = dict(name="dark", bg="#0A0A09", panel="#121211", panel2="#1A1A19", line="#2B2B28", text="#ECE8DE", mute="#97938A",
            accent="#BFD0AE", pos="#8FC49A", neg="#E0806F", warn="#D9B26F",
            c=["#50A460", "#3890D2", "#D15D51", "#B066B4", "#AF8E2A"], grid="rgba(236,232,222,0.075)",
            accent_a="rgba(191,208,174,0.07)")
LIGHT = DARK  # v2 is black-only by design


def theme():
    return DARK


FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600"
         "&family=Inter:wght@400;500;600&display=swap")
SERIF = "'Fraunces',Georgia,'Times New Roman',serif"
SANS = "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif"

_run_ids: dict = {}


def _rings_uri(th) -> str:
    """Tree-ring contours (static). Polar curves with low-frequency wobble: organic, topographic, quiet."""
    paths = []
    for i in range(26):
        r0, ph = 46 + i * 41, i * 0.55
        pts = []
        for k in range(0, 361, 3):
            a = math.radians(k)
            r = r0 * (1 + 0.07 * math.sin(3 * a + ph) + 0.045 * math.sin(5 * a - ph * 1.7) + 0.02 * math.sin(9 * a + ph * 2.3))
            pts.append(f"{1180 + r * math.cos(a):.1f},{930 + r * 0.82 * math.sin(a):.1f}")
        paths.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="{th["text"]}" stroke-opacity="{0.055 - i * 0.0012:.4f}" stroke-width="1" stroke-linejoin="round"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" preserveAspectRatio="xMaxYMax slice">{"".join(paths)}</svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _grain_uri() -> str:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><filter id="n"><feTurbulence type="fractalNoise" '
           'baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .55 0"/></filter>'
           '<rect width="100%" height="100%" filter="url(#n)"/></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _spores(th) -> str:
    out = []
    for i in range(14):
        h = int(hashlib.md5(f"s{i}".encode()).hexdigest(), 16)
        x, y = (h % 100), ((h >> 8) % 70) + 25
        size, dur, dly = 2 + (h >> 16) % 3, 22 + (h >> 20) % 18, -((h >> 26) % 30)
        out.append(f'<i style="left:{x}%;top:{y}%;width:{size}px;height:{size}px;animation-duration:{dur}s;animation-delay:{dly}s"></i>')
    return f'<div class="qd-spores" aria-hidden="true">{"".join(out)}</div>'


def inject_css(th):
    _run_ids.clear()
    st.markdown(f"""
<style>
@import url('{FONTS}');
:root {{ --qd-bg:{th['bg']}; --qd-panel:{th['panel']}; --qd-panel2:{th['panel2']}; --qd-line:{th['line']};
  --qd-text:{th['text']}; --qd-mute:{th['mute']}; --qd-accent:{th['accent']}; --qd-pos:{th['pos']}; --qd-neg:{th['neg']}; --qd-warn:{th['warn']};
  --qd-ease:cubic-bezier(.22,.9,.28,1); --qd-hair:rgba(236,232,222,.08); --qd-glass:rgba(236,232,222,.045); }}
.stApp {{ background:var(--qd-bg); color:var(--qd-text); }}
/* static atmosphere: warm vignette + tree rings + grain (no per-frame cost) */
.stApp::before {{ content:''; position:fixed; inset:0; z-index:0; pointer-events:none;
  background:radial-gradient(1100px 620px at 12% -8%, rgba(191,208,174,.075), transparent 60%),
             radial-gradient(900px 600px at 100% 100%, rgba(217,178,111,.05), transparent 60%),
             url("{_rings_uri(th)}") right bottom / cover no-repeat; }}
.stApp::after {{ content:''; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.035; background:url("{_grain_uri()}"); mix-blend-mode:overlay; }}
[data-testid="stMain"], [data-testid="stSidebar"], [data-testid="stHeader"] {{ position:relative; z-index:1; }}
[data-testid="stHeader"] {{ background:transparent; }}
.stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea, .stApp button {{ font-family:{SANS}; }}
.block-container {{ padding-top:1.8rem; max-width:1320px; }}
h1,h2,h3,.qd-title,.qd-h {{ font-family:{SERIF} !important; font-weight:400 !important; letter-spacing:-0.015em; }}
/* living elements: spores drift (transform/opacity only) */
.qd-spores {{ position:fixed; inset:0; z-index:0; pointer-events:none; overflow:hidden; }}
.qd-spores i {{ position:absolute; border-radius:50%; background:var(--qd-accent); opacity:0; animation:qd-drift linear infinite; will-change:transform,opacity; }}
@keyframes qd-drift {{ 0% {{ transform:translate3d(0,0,0); opacity:0; }} 15% {{ opacity:.45; }} 85% {{ opacity:.25; }} 100% {{ transform:translate3d(30px,-160px,0); opacity:0; }} }}
/* tabs: glass pill (Streamlit 1.65 react-aria markup) */
[role="tablist"] {{ gap:4px; padding:5px; width:fit-content; border-radius:99px; background:var(--qd-glass); border:1px solid var(--qd-hair); position:relative;
  -webkit-backdrop-filter:blur(14px) saturate(160%); backdrop-filter:blur(14px) saturate(160%); box-shadow:inset 0 1px 0 rgba(236,232,222,.06); }}
[data-testid="stTab"] {{ height:38px; padding:0 20px; border-radius:99px; display:flex; align-items:center; position:relative; transition:background .25s var(--qd-ease), color .25s var(--qd-ease); }}
[data-testid="stTab"] p {{ font-weight:500; font-size:.93rem; }}
[data-testid="stTab"]:hover {{ background:rgba(236,232,222,.06); }}
[data-testid="stTab"][aria-selected="true"] {{ color:var(--qd-accent); }}
[data-testid="stTab"] .react-aria-SelectionIndicator {{ position:absolute !important; inset:0 !important; height:auto !important; border-radius:99px !important; background:rgba(191,208,174,.11) !important; box-shadow:inset 0 0 0 1px rgba(191,208,174,.22) !important; z-index:-1; transition:all .4s var(--qd-ease); }}
/* hero */
.qd-hero {{ position:relative; display:flex; align-items:flex-end; justify-content:space-between; gap:24px; padding:34px 36px 30px; margin-bottom:18px;
  border:1px solid var(--qd-hair); border-radius:32px; overflow:hidden;
  background:linear-gradient(160deg, rgba(236,232,222,.05) 0%, rgba(236,232,222,.012) 70%); box-shadow:inset 0 1px 0 rgba(236,232,222,.06), 0 30px 80px rgba(0,0,0,.45); }}
.qd-title {{ font-size:2.7rem; line-height:1.05; margin:0; color:var(--qd-text); font-weight:300 !important; }}
.qd-title em {{ font-style:italic; color:var(--qd-accent); }}
.qd-sub {{ color:var(--qd-mute); font-size:.95rem; margin-top:8px; max-width:560px; line-height:1.5; }}
.qd-ribbon {{ position:absolute; right:0; top:0; height:100%; width:56%; pointer-events:none; }}
.qd-ribbon g {{ transform-origin:50% 100%; animation:qd-breathe 9s ease-in-out infinite alternate; }}
.qd-ribbon path {{ fill:none; stroke-linecap:round; stroke-dasharray:1400; stroke-dashoffset:1400; animation:qd-draw 2.4s var(--qd-ease) forwards; }}
.qd-ribbon path:nth-child(2) {{ animation-delay:.2s; }} .qd-ribbon path:nth-child(3) {{ animation-delay:.4s; }}
@keyframes qd-draw {{ to {{ stroke-dashoffset:0; }} }}
@keyframes qd-breathe {{ from {{ transform:scaleY(1); }} to {{ transform:scaleY(1.07); }} }}
.qd-badge {{ display:inline-flex; align-items:center; gap:8px; padding:5px 13px; border-radius:99px; font-size:.76rem; font-weight:500; letter-spacing:.02em;
  border:1px solid var(--qd-hair); background:var(--qd-glass); color:var(--qd-text); -webkit-backdrop-filter:blur(12px); backdrop-filter:blur(12px); }}
.qd-badge i {{ width:7px; height:7px; border-radius:50%; background:var(--qd-pos); display:inline-block; }}
.qd-badge.demo i {{ background:var(--qd-warn); animation:qd-pulse 2.4s ease-in-out infinite; }}
.qd-badge.live i {{ animation:qd-pulse 3.2s ease-in-out infinite; }}
@keyframes qd-pulse {{ 50% {{ opacity:.35; transform:scale(.78); }} }}
/* cards & notes */
.qd-card {{ border:1px solid var(--qd-hair); background:linear-gradient(180deg,rgba(236,232,222,.04),rgba(236,232,222,.012)); border-radius:24px; padding:16px 20px; box-shadow:inset 0 1px 0 rgba(236,232,222,.05); }}
.qd-note {{ border:1px solid var(--qd-hair); border-left:2px solid var(--qd-accent); background:var(--qd-glass); border-radius:6px 20px 20px 6px; padding:12px 18px; margin:8px 0; color:var(--qd-text); font-size:.92rem; line-height:1.55; }}
.qd-note.warn {{ border-left-color:var(--qd-warn); }} .qd-note.neg {{ border-left-color:var(--qd-neg); }} .qd-note.pos {{ border-left-color:var(--qd-pos); }}
.qd-note b {{ font-weight:600; }}
.qd-sec {{ font-family:{SERIF}; font-weight:400; font-size:1.45rem; letter-spacing:-.01em; margin:26px 0 6px 0; color:var(--qd-text); }}
.qd-sec small {{ font-family:{SANS}; font-weight:400; color:var(--qd-mute); margin-left:12px; font-size:.82rem; letter-spacing:0; }}
.qd-pill {{ display:inline-block; padding:3px 12px; margin:2px 6px 2px 0; border-radius:99px; font-size:.78rem; background:var(--qd-glass); border:1px solid var(--qd-hair); color:var(--qd-mute); }}
.qd-reco {{ margin-bottom:8px; border:1px solid var(--qd-hair); background:linear-gradient(180deg,rgba(236,232,222,.045),rgba(236,232,222,.012)); border-radius:24px; padding:18px 20px; height:100%;
  box-shadow:inset 0 1px 0 rgba(236,232,222,.05); transition:border-color .3s var(--qd-ease), transform .3s var(--qd-ease); }}
.qd-reco:hover {{ border-color:rgba(191,208,174,.45); transform:translateY(-2px); }}
.qd-reco h4 {{ font-family:{SERIF}; font-weight:400; margin:0 0 4px 0; font-size:1.2rem; }}
.qd-reco p {{ margin:4px 0; color:var(--qd-mute); font-size:.86rem; }}
div[data-testid="stDataFrame"] {{ border:1px solid var(--qd-hair); border-radius:18px; overflow:hidden; }}
.stButton > button, .stDownloadButton > button {{ border-radius:99px; border:1px solid var(--qd-hair); background:var(--qd-glass); transition:transform .12s var(--qd-ease), border-color .25s var(--qd-ease); }}
.stButton > button:hover {{ border-color:rgba(191,208,174,.5); }} .stButton > button:active {{ transform:scale(.98); }}
@media (prefers-reduced-motion: reduce) {{ .qd-ribbon path {{ animation:none; stroke-dashoffset:0; }} .qd-ribbon g, .qd-spores i, .qd-badge i {{ animation:none !important; }} .qd-spores {{ display:none; }} }}
.js-plotly-plot .scatterlayer .js-line:not([style*="dasharray"]) {{ stroke-dasharray:4000; stroke-dashoffset:4000; animation:qd-draw 1.4s var(--qd-ease) forwards; }}
</style>{_spores(th)}""", unsafe_allow_html=True)


def hero(th, title, sub, source, note=""):
    cls = "live" if source == "LIVE" else "demo"
    c = th["c"]
    svg = f"""<svg class="qd-ribbon" viewBox="0 0 520 160" preserveAspectRatio="none"><defs>
<linearGradient id="g1" x1="0" x2="1"><stop offset="0" stop-color="{c[0]}" stop-opacity="0"/><stop offset=".4" stop-color="{c[0]}" stop-opacity=".85"/><stop offset="1" stop-color="{th['accent']}"/></linearGradient>
<linearGradient id="g2" x1="0" x2="1"><stop offset="0" stop-color="{th['warn']}" stop-opacity="0"/><stop offset=".6" stop-color="{th['warn']}" stop-opacity=".45"/><stop offset="1" stop-color="{th['warn']}" stop-opacity=".7"/></linearGradient></defs><g>
<path d="M0,132 C90,128 140,108 205,86 S340,52 410,44 S490,42 520,36" stroke="url(#g1)" stroke-width="2.4"/>
<path d="M0,142 C100,138 160,126 225,108 S350,82 420,78 S495,74 520,70" stroke="url(#g2)" stroke-width="1.5"/>
<path d="M0,118 C80,120 150,86 215,66 S330,30 400,22 S480,28 520,14" stroke="{th['text']}" stroke-opacity=".22" stroke-width="1"/></g></svg>"""
    t1, _, t2 = title.partition(" ")
    st.markdown(f"""<div class="qd-hero">{svg}<div style="position:relative;z-index:1">
<div class="qd-title">{t1} <em>{t2}</em></div><div class="qd-sub">{sub}</div><div class="qd-sub" style="margin-top:12px;font-size:.8rem">{note}</div></div>
<div style="position:relative;z-index:1;text-align:right"><span class="qd-badge {cls}"><i></i>{source}</span></div></div>""", unsafe_allow_html=True)


def section(title, sub=""):
    st.markdown(f'<div class="qd-sec">{title}<small>{sub}</small></div>', unsafe_allow_html=True)


def note(text, kind=""):
    st.markdown(f'<div class="qd-note {kind}">{text}</div>', unsafe_allow_html=True)


def plotly_layout(th, height=420, **kw):
    base = dict(template="plotly_dark", height=height,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=th["c"],
                font=dict(family="Inter, system-ui, sans-serif", color=th["text"], size=12),
                margin=dict(l=8, r=8, t=36, b=8), hovermode="x unified",
                xaxis=dict(gridcolor=th["grid"], zerolinecolor=th["grid"], showline=False),
                yaxis=dict(gridcolor=th["grid"], zerolinecolor=th["grid"], showline=False),
                legend=dict(orientation="h", y=1.1, x=0, bgcolor="rgba(0,0,0,0)"),
                hoverlabel=dict(bgcolor=th["panel2"], bordercolor=th["line"], font=dict(color=th["text"])))
    base.update(kw)
    return base


# ------------------------------------------------------------------------- spring KPI strip (components v2, in-page)
_KPI_CSS = f"""
.g {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr)); gap:12px; font-family:{SANS}; }}
.k {{ position:relative; overflow:hidden; border:1px solid var(--hair); border-radius:24px; padding:16px 18px 14px; color:var(--text);
  background:linear-gradient(180deg,rgba(236,232,222,.05),rgba(236,232,222,.014)); box-shadow:inset 0 1px 0 rgba(236,232,222,.06); opacity:0; transform:translate3d(0,8px,0) scale(.985);
  transition:opacity .5s cubic-bezier(.22,.9,.28,1), transform .5s cubic-bezier(.22,.9,.28,1), border-color .3s; }}
.k.in {{ opacity:1; transform:none; }}
.k:hover {{ border-color:rgba(191,208,174,.35); }}
.k::after {{ content:''; position:absolute; inset:0; border-radius:inherit; background:var(--tint,transparent); opacity:0; pointer-events:none; }}
.k.flash::after {{ animation:fl .9s ease-out; }}
@keyframes fl {{ 0% {{ opacity:.20; }} 100% {{ opacity:0; }} }}
.l {{ font-size:12px; color:var(--mute); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; letter-spacing:.01em; }}
.v {{ font-family:{SERIF}; font-weight:300; font-size:30px; line-height:1.15; margin-top:4px; font-variant-numeric:tabular-nums lining-nums; letter-spacing:-.01em; }}
.s {{ font-size:11.5px; color:var(--mute); margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-height:14px; }}
.dot {{ position:absolute; right:16px; top:16px; width:6px; height:6px; border-radius:50%; background:var(--mute); opacity:.55; }}
.k.pos .v {{ color:var(--pos); }} .k.neg .v {{ color:var(--neg); }} .k.acc .v {{ color:var(--accent); }}
.k.pos .dot {{ background:var(--pos); opacity:1; }} .k.neg .dot {{ background:var(--neg); opacity:1; }} .k.acc .dot {{ background:var(--accent); opacity:1; }}
@media (prefers-reduced-motion: reduce) {{ .k {{ transition:none; transform:none; }} .k.flash::after {{ animation:none; }} }}
"""

_KPI_JS = core_js() + r"""
export default function (component) {
  const {data, parentElement: root} = component;
  const S = root.__qdKpi || (root.__qdKpi = {springs: [], nodes: [], sig: ''});
  const items = data.items, sig = items.map(i => i.label).join('|');
  let g = root.querySelector('.g');
  if (!g || S.sig !== sig) {                                   // (re)build only when the set of cards changes
    if (g) g.remove();
    g = document.createElement('div'); g.className = 'g'; root.appendChild(g); S.springs = []; S.nodes = []; S.sig = sig;
    items.forEach((it, i) => {
      const d = document.createElement('div'); d.className = 'k ' + (it.tone || '');
      d.innerHTML = '<span class="dot"></span><div class="l"></div><div class="v"></div><div class="s"></div>'; g.appendChild(d);
      const sp = new QD.Spring(0, 'glide'); const n = d.querySelector('.v');
      sp.onUpdate = x => { const it2 = S.items[i]; n.textContent = QD.num(x, it2.dec, it2.prefix, it2.suffix); };
      S.springs.push(sp); S.nodes.push(d);
      setTimeout(() => d.classList.add('in'), QD.reduce ? 0 : 70 * i);  // staged entrance, 70 ms offsets
    });
    S.first = true;
  }
  Object.entries(data.th).forEach(([k, v]) => g.style.setProperty('--' + k, v));
  const prev = S.items; S.items = items;
  items.forEach((it, i) => {
    const d = S.nodes[i], sp = S.springs[i], n = d.querySelector('.v');
    d.className = d.className.replace(/\b(pos|neg|acc)\b/g, '').trim() + ' ' + (it.tone || '');
    d.querySelector('.l').textContent = it.label; d.querySelector('.s').innerHTML = it.sub || '&nbsp;';
    if (it.value === null || it.value === undefined || isNaN(it.value)) { sp.jump(0); n.textContent = '—'; sp.onUpdate = null; return; }
    sp.onUpdate = x => { const c = S.items[i]; n.textContent = QD.num(x, c.dec, c.prefix, c.suffix); };
    const changed = prev && prev[i] && prev[i].value !== it.value;
    if (changed) {                                                // redirect from where the number is now
      d.style.setProperty('--tint', it.value > prev[i].value ? 'var(--pos)' : 'var(--neg)');
      d.classList.remove('flash'); void d.offsetWidth; d.classList.add('flash');
    }
    sp.to(it.value, S.first ? 70 * i + 120 : 0);
  });
  S.first = false;
}
"""

_kpi_comp = None


def kpi_strip(th, items, height=None):
    """items: [{label, value, dec, prefix, suffix, sub, tone}]. First paint: staged spring count-up; later runs: numbers
    spring from their current value to the new one (redirectable) and tick-flash green/red by direction."""
    global _kpi_comp
    if _kpi_comp is None:
        _kpi_comp = st.components.v2.component("qd_kpi_v2", css=_KPI_CSS, js=_KPI_JS, isolate_styles=True)
    its = [{**{"dec": 2, "prefix": "", "suffix": "", "sub": "", "tone": ""}, **i} for i in items]
    for i in its:
        v = i.get("value")
        i["value"] = None if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else float(v)
    base = hashlib.md5("|".join(i["label"] for i in its).encode()).hexdigest()[:8]
    n = _run_ids[base] = _run_ids.get(base, 0) + 1
    thp = {k: th[k] for k in ("text", "mute", "accent", "pos", "neg", "warn")}
    thp["hair"] = "rgba(236,232,222,.08)"
    _kpi_comp(data={"items": its, "th": thp}, key=f"kpi_{base}_{n}")


_IFRAME_CSS = """
@import url('%(fonts)s');
*{box-sizing:border-box;margin:0} body{background:transparent;font-family:'Inter',system-ui,sans-serif;color:%(text)s}
"""


def _clean(x):
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_clean(i) for i in x]
    if x is None:
        return None
    x = float(x)
    return None if (np.isnan(x) or np.isinf(x)) else round(x, 6)


def lattice_player(th, trees, bs, cp, labels, height=510):
    """trees: list (N=1..10) of crr() dicts. Interactive animated lattice with convergence panel.
    labels: dict of translated UI strings."""
    data = []
    for t in trees:
        data.append({"S": [_clean(a) for a in t["spot"]], "V": [_clean(a) for a in t["value"]],
                     "D": [_clean(a) for a in t["delta"]] + [None], "G": [_clean(a) for a in t["gamma"]] + [None, None],
                     "X": [[bool(b) for b in a] for a in t["exercise"]],
                     "price": _clean(t["price"]), "delta0": _clean(t["delta0"]), "gamma0": _clean(t["gamma0"]),
                     "theta0": _clean(t["theta0"]), "u": _clean(t["u"]), "p": _clean(t["p"])})
    payload = json.dumps({"trees": data, "bs": {k: _clean(v) for k, v in bs.items()}, "cp": cp, "L": labels})
    html = f"""<style>{_IFRAME_CSS % dict(fonts=FONTS, text=th['text'])}
.w{{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(250px,1fr);gap:12px}}
.p{{background:{th['panel']};border:1px solid {th['line']};border-radius:22px;padding:12px}}
.bar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;font-size:12.5px}}
button{{font:600 12.5px 'Inter',system-ui,sans-serif;color:{th['text']};background:{th['panel2']};border:1px solid {th['line']};border-radius:99px;padding:6px 14px;cursor:pointer;transition:all .15s}}
button:hover{{border-color:{th['accent']}}} button.on{{background:{th['accent']};color:{th['bg']};border-color:{th['accent']}}}
input[type=range]{{accent-color:{th['accent']};width:150px}}
.n{{font-family:'Fraunces',Georgia,serif;font-weight:600;color:{th['accent']};min-width:70px}}
svg text{{font-family:'Inter',system-ui,sans-serif;fill:{th['mute']};font-size:10.5px}} svg .big{{fill:{th['text']};font-size:10px;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}} td,th{{padding:5px 4px;text-align:right;border-bottom:1px solid {th['line']}}}
th{{color:{th['mute']};font-weight:500}} td:first-child,th:first-child{{text-align:left}}
.tip{{position:absolute;pointer-events:none;background:{th['panel2']};border:1px solid {th['line']};border-radius:10px;padding:7px 10px;font-size:12px;display:none;z-index:9;line-height:1.5}}
.node{{transition:r .2s,opacity .35s}} .edge{{transition:opacity .35s}}
</style>
<div class="w"><div class="p" style="position:relative">
<div class="bar"><button id="play"></button><span id="nlab" class="n"></span><input id="rng" type="range" min="1" max="10" value="10">
<button id="back"></button><span style="flex:1"></span>
<span id="mets"></span></div>
<svg id="svg" viewBox="0 0 760 430" width="100%"></svg><div class="tip" id="tip"></div></div>
<div class="p"><div style="font:600 13px Fraunces,Georgia,serif;margin-bottom:2px" id="ctitle"></div><svg id="conv" viewBox="0 0 300 190" width="100%"></svg>
<table id="tbl"></table></div></div>
<script>
const P={payload};const T=P.trees,L=P.L,BS=P.bs,TH={json.dumps({k: th[k] for k in ('accent','mute','text','line','warn','panel2','bg')})};
let N=10,met='V',revealed=99,timer=null;const NS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id),el=(n,a,p)=>{{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}};
$('play').textContent='▶ '+L.play;$('back').textContent=L.back;$('ctitle').textContent=L.conv;
const mets=[['V',L.value],['S',L.spot],['D','Δ'],['G','Γ']];
mets.forEach(([k,n])=>{{const b=document.createElement('button');b.textContent=n;b.dataset.k=k;b.onclick=()=>{{met=k;draw()}};$('mets').appendChild(b)}});
function color(v,lo,hi){{if(v==null)return TH.line;const t=hi>lo?(v-lo)/(hi-lo):.5;
 const a=[hex(TH.line),hex(TH.accent)];const c=a[0].map((x,i)=>Math.round(x+(a[1][i]-x)*Math.pow(t,.8)));return `rgb(${{c}})`}}
function hex(h){{h=h.replace('#','');return [0,2,4].map(i=>parseInt(h.substr(i,2),16))}}
function fmt(x,d=3){{return x==null?'—':x.toFixed(d)}}
function draw(){{const t=T[N-1],svg=$('svg');svg.innerHTML='';$('nlab').textContent='N = '+N;$('rng').value=N;
 document.querySelectorAll('#mets button').forEach(b=>b.classList.toggle('on',b.dataset.k===met));
 const W=760,H=430,mx=44,my=26,dx=N>0?(W-2*mx)/N:0,dy=Math.min(34,(H-2*my)/Math.max(N,1));
 const X=i=>mx+i*dx,Y=(i,j)=>H/2+(j-i/2)*dy;
 const layer=t[met==='V'?'V':met==='S'?'S':met==='D'?'D':'G'];
 let all=[];layer.forEach(a=>a&&a.forEach(v=>v!=null&&all.push(v)));const lo=Math.min(...all),hi=Math.max(...all);
 for(let i=0;i<N;i++)for(let j=0;j<=i;j++){{[[i+1,j],[i+1,j+1]].forEach(([i2,j2],k)=>{{
   const e=el('line',{{x1:X(i),y1:Y(i,j),x2:X(i2),y2:Y(i2,j2),stroke:TH.line,'stroke-width':1,class:'edge'}},svg);
   e.style.opacity=0.9}})}}
 const tip=$('tip');
 for(let i=0;i<=N;i++)for(let j=0;j<=i;j++){{const v=layer[i]?layer[i][j]:null;
   const on=i>=N-(revealed===99?99:0)||true;const dim=(revealed!==99&&i<revealed);
   const c=el('circle',{{cx:X(i),cy:Y(i,j),r:N>7?6.5:N>4?8.5:11,fill:color(v,lo,hi),stroke:t.X[i]&&t.X[i][j]?TH.warn:'none','stroke-width':2.4,class:'node'}},svg);
   c.style.opacity=dim?0.18:1;c.style.cursor='pointer';
   c.addEventListener('mouseenter',e=>{{tip.style.display='block';tip.innerHTML=`<b>${{L.layer}} ${{i}} · ${{L.node}} ${{j}}</b><br>S = ${{fmt(t.S[i][j],2)}}<br>${{L.value}} = ${{fmt(t.V[i][j],4)}}<br>Δ = ${{fmt(t.D[i]?t.D[i][j]:null,4)}}<br>Γ = ${{fmt(t.G[i]?t.G[i][j]:null,5)}}${{t.X[i][j]?'<br><span style="color:'+TH.warn+'">'+L.exercise+'</span>':''}}`}});
   c.addEventListener('mousemove',e=>{{const r=svg.parentNode.getBoundingClientRect();tip.style.left=(e.clientX-r.left+14)+'px';tip.style.top=(e.clientY-r.top+14)+'px'}});
   c.addEventListener('mouseleave',()=>tip.style.display='none');
   if(N<=5&&!dim){{el('text',{{x:X(i),y:Y(i,j)+3.5,'text-anchor':'middle',class:'big',style:'fill:'+TH.bg}},svg).textContent=met==='G'||met==='D'?fmt(v,met==='G'?3:2):fmt(v,met==='S'?1:2)}}}}
 for(let i=0;i<=N;i++)el('text',{{x:X(i),y:H-6,'text-anchor':'middle'}},svg).textContent='t'+i;
 // convergence
 const cv=$('conv');cv.innerHTML='';const CW=300,CH=190,l=36,r=8,tp=10,b=24;
 const ps=T.map(x=>x.price),ymin=Math.min(...ps,BS.price)*0.97,ymax=Math.max(...ps,BS.price)*1.03;
 const cx=n=>l+(n-1)/9*(CW-l-r),cy=v=>CH-b-(v-ymin)/(ymax-ymin)*(CH-b-tp);
 el('line',{{x1:l,x2:CW-r,y1:cy(BS.price),y2:cy(BS.price),stroke:TH.warn,'stroke-dasharray':'4 3','stroke-width':1.4}},cv);
 el('text',{{x:CW-r,y:cy(BS.price)-4,'text-anchor':'end',style:'fill:'+TH.warn}},cv).textContent='BSM '+fmt(BS.price,3);
 el('polyline',{{points:ps.map((v,k)=>cx(k+1)+','+cy(v)).join(' '),fill:'none',stroke:TH.accent,'stroke-width':2,'stroke-linejoin':'round'}},cv);
 ps.forEach((v,k)=>el('circle',{{cx:cx(k+1),cy:cy(v),r:k+1===N?5:2.5,fill:k+1===N?TH.accent:TH.mute}},cv));
 for(let n=1;n<=10;n+=3)el('text',{{x:cx(n),y:CH-8,'text-anchor':'middle'}},cv).textContent=n;
 [ymin,(ymin+ymax)/2,ymax].forEach(v=>el('text',{{x:l-4,y:cy(v)+3,'text-anchor':'end'}},cv).textContent=v.toFixed(2));
 const err=t.price-BS.price;
 $('tbl').innerHTML=`<tr><th></th><th>${{L.tree}}</th><th>BSM</th></tr><tr><td>${{L.price}}</td><td>${{fmt(t.price,4)}}</td><td>${{fmt(BS.price,4)}}</td></tr>
 <tr><td>${{L.error}}</td><td>${{(err>=0?'+':'')+fmt(err,4)}}</td><td></td></tr>
 <tr><td>Δ</td><td>${{fmt(t.delta0,4)}}</td><td>${{fmt(BS.delta,4)}}</td></tr><tr><td>Γ</td><td>${{fmt(t.gamma0,5)}}</td><td>${{fmt(BS.gamma,5)}}</td></tr>
 <tr><td>Θ/${{L.day}}</td><td>${{fmt(t.theta0,4)}}</td><td>${{fmt(BS.theta,4)}}</td></tr><tr><td>u · p</td><td colspan=2>${{fmt(t.u,4)}} · ${{fmt(t.p,4)}}</td></tr>`;}}
$('rng').oninput=e=>{{N=+e.target.value;revealed=99;draw()}};
$('play').onclick=()=>{{if(timer){{clearInterval(timer);timer=null;return}};N=1;revealed=99;draw();
 timer=setInterval(()=>{{if(N>=10){{clearInterval(timer);timer=null;return}};N++;draw()}},650)}};
$('back').onclick=()=>{{if(timer)clearInterval(timer);revealed=N;draw();
 timer=setInterval(()=>{{revealed--;draw();if(revealed<0){{clearInterval(timer);timer=null;revealed=99;draw()}}}},520)}};
draw();
</script>"""
    st.iframe(html, height=height)

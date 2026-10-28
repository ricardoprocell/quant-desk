"""Quant Desk v2 - motion core (shared JS) and motion tokens.

Physics follows the design brief: springs defined by (response, damping ratio), interruptible and
redirectable (a new target keeps the current velocity), one shared requestAnimationFrame loop,
transform/opacity only, reduced-motion snaps instantly.
"""

# name -> (response seconds, damping ratio)
TOKENS = {"press": (0.10, 1.0), "snap": (0.25, 1.0), "settle": (0.45, 1.0), "glide": (0.55, 0.9), "bounce": (0.40, 0.7)}

CORE_JS = r"""
const QD = (() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const TOK = %(tokens)s;
  const live = new Set(); let raf = 0, last = 0;
  function frame(ts) {
    raf = 0; const dt = Math.min((ts - last) / 1000 || 1/60, 1/20); last = ts;
    const n = Math.max(1, Math.ceil(dt * 120)), h = dt / n;
    for (const s of [...live]) {
      for (let i = 0; i < n; i++) s._step(h);
      if (s.done()) { s.x = s.t; s.v = 0; live.delete(s); }
      if (s.onUpdate) s.onUpdate(s.x, s);
    }
    if (live.size) raf = requestAnimationFrame(frame);
  }
  class Spring {
    constructor(x = 0, tok = 'glide') { this.x = x; this.t = x; this.v = 0; this.use(tok); }
    use(tok) { const [r, z] = typeof tok === 'string' ? TOK[tok] : tok; const w = 2 * Math.PI / r; this.k = w * w; this.c = 2 * z * w; return this; }
    _step(h) { this.v += (-this.k * (this.x - this.t) - this.c * this.v) * h; this.x += this.v * h; }
    done() { return Math.abs(this.x - this.t) < 1e-4 * (1 + Math.abs(this.t)) && Math.abs(this.v) < 1e-3 * (1 + Math.abs(this.t)); }
    to(t, delay = 0) {            // redirect: position and velocity are preserved
      const go = () => { this.t = t;
        if (reduce) { this.x = t; this.v = 0; live.delete(this); if (this.onUpdate) this.onUpdate(this.x, this); return; }
        live.add(this); if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); } };
      if (delay && !reduce) setTimeout(go, delay); else go(); return this; }
    jump(x) { this.x = this.t = x; this.v = 0; live.delete(this); if (this.onUpdate) this.onUpdate(x, this); }
  }
  const fmt = (x, d) => x.toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
  // number text: minus sign before prefix, never "-0.00"
  const num = (v, d, pre = '', suf = '') => (v < 0 && Math.abs(v) >= Math.pow(10, -d) / 2 ? '−' : '') + pre + fmt(Math.abs(v), d) + suf;
  return {Spring, reduce, num, fmt, TOK};
})();
"""


def core_js() -> str:
    import json
    return CORE_JS % {"tokens": json.dumps({k: list(v) for k, v in TOKENS.items()})}

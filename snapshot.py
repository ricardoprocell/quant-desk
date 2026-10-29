"""Fetch market data (FRED + Yahoo) from THIS machine and write snapshot.json.
Runs on a schedule in GitHub Actions (see .github/workflows/snapshot.yml) or by hand: `python snapshot.py`.
The Streamlit app reads the published file when Yahoo blocks its own server. Nothing is written if too little data came back."""
import datetime as dt
import json
import os
import sys
import time

os.environ["QD_NO_SNAPSHOT"] = "1"
import qd_data as D  # noqa: E402

TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GLD", "USO"]
N_EXPIRIES = 5
OUT = sys.argv[1] if len(sys.argv) > 1 else "snapshot.json"


def main():
    snap = {"generated_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "curve": {}, "commodities": {}, "underlyings": {}}
    q, meta, _ = D.fetch_curve()
    if meta["source"] == "LIVE":
        snap["curve"] = {"quotes": q, "asof": meta["asof"]}
    print("curve:", meta["source"], meta["note"])
    for key in D.COMMODITIES:
        spot, df, m = D.fetch_commodity(key)
        print(key, m["source"], m["note"])
        if m["source"] == "LIVE":
            snap["commodities"][key] = {"spot": float(spot), "rows": [{"ticker": r.ticker, "expiry": r.expiry.isoformat(), "price": float(r.price)} for r in df.itertuples()]}
    for tk in TICKERS:
        h, qd, exps, m = D.fetch_underlying(tk)
        print(tk, m["source"], m["note"][:70])
        if m["source"] != "LIVE":
            continue
        S = float(h.iloc[-1])
        chains = {}
        for e in exps[:N_EXPIRIES]:
            T = max((dt.date.fromisoformat(e) - dt.date.today()).days, 1) / 365.0
            ch, cm = D.fetch_chain(tk, e, S, T)
            if cm["source"] == "LIVE" and len(ch) >= 6:
                chains[e] = [[float(r.strike), r.cp, round(float(r.mid), 4)] for r in ch.itertuples()]
            time.sleep(0.7)
        if chains:
            snap["underlyings"][tk] = {"closes": [[str(i.date()), round(float(v), 4)] for i, v in h.tail(260).items()], "q": float(qd), "expiries": list(chains), "chains": chains}
        time.sleep(0.7)
    got = bool(snap["curve"]) + len(snap["commodities"]) + len(snap["underlyings"])
    print("sections with data:", got)
    if got < 2:
        print("Too little live data; not writing a snapshot.")
        sys.exit(1)
    with open(OUT, "w") as f:
        json.dump(snap, f, separators=(",", ":"))
    print("wrote", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()

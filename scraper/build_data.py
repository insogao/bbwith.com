"""Turn a raw crawl into normalized monthly prices.

python scraper/build_data.py [YYYY-MM-DD]  -> data/daily/<date>.json (compact history, committed)
"""
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from normalize import parse  # noqa: E402
from plans import PLANS  # noqa: E402

ANNUAL_FACTOR = 5  # a price above 5x the US monthly price is treated as annual


def build(day):
    raw = json.load(open(os.path.join(ROOT, "data", "raw", f"{day}.json")))
    fx = json.load(open(os.path.join(ROOT, "data", "raw", f"fx-{day}.json")))
    rates = fx["rates"]
    by = {(app, cc): (st, items) for app, cc, st, items in raw}
    ccs = sorted({cc for _, cc, _, _ in raw})
    unavailable = {}
    for (app, cc), (st, _) in by.items():
        if st == 404:
            unavailable.setdefault(app, []).append(cc)

    def values(cc, rules):
        out = []
        for app, rx in rules:
            st, items = by.get((app, cc), (None, []))
            for name, price in items:
                if re.search(rx, name):
                    try:
                        cur, v = parse(cc, price)
                    except Exception:
                        continue
                    if cur not in rates:
                        continue
                    out.append((v / rates[cur], cur, v, price.replace("\xa0", " ").replace(" ", " ")))
        return out

    rows = []
    for product, plan, label, rules in PLANS:
        us = values("us", rules)
        if not us:
            continue
        ref = min(u[0] for u in us)
        for cc in ccs:
            monthly = [x for x in values(cc, rules) if x[0] < ref * ANNUAL_FACTOR]
            if not monthly:
                continue
            best = max(monthly)  # regular price; intro offers are lower
            rows.append({
                "product": product, "plan": plan, "label": label, "cc": cc,
                "currency": best[1], "local": best[2], "display": best[3],
                "usd": round(best[0], 2), "cny": round(best[0] * rates["CNY"], 2),
                "vs_us": round(best[0] / ref - 1, 4),
                "multi": len({round(x[0], 2) for x in monthly}) > 1,
            })
    # compact history: local price per plan/storefront, plus the currency and FX rate used
    hist = {"date": day, "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"), "fx_source": "open.er-api.com", "fx_updated": fx["time_last_update_utc"],
            "usd_cny": rates["CNY"], "storefronts": ccs, "unavailable": unavailable, "cur": {}, "fx": {}, "disp": {}, "p": {}}
    for r in rows:
        hist["cur"][r["cc"]] = r["currency"]
        hist["fx"][r["currency"]] = rates[r["currency"]]
        hist["p"].setdefault(f'{r["product"]}/{r["plan"]}', {})[r["cc"]] = r["local"]
        hist["disp"].setdefault(f'{r["product"]}/{r["plan"]}', {})[r["cc"]] = r["display"]
    os.makedirs(os.path.join(ROOT, "data", "daily"), exist_ok=True)
    json.dump(hist, open(os.path.join(ROOT, "data", "daily", f"{day}.json"), "w"), separators=(",", ":"))
    print(day, len(rows), "rows")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        day = sys.argv[1]
    else:
        day = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(ROOT, "data", "raw", "20*.json")))[-1]
    build(day)

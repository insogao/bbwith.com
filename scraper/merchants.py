"""Verify merchant listings and compute credit scores (run in GitHub Actions every few hours).

Reads approved listings from https://bbwith.com/api/listings, opens each product page, checks that the
declared price appears on it and that it is not marked out of stock, keeps a check history and writes
data/merchants/latest.json for the site generator.

Score (0-100), documented on /about/:
  价格核验 30  自动核价 30 小时内通过 30 / 管理员 7 天内人工核过 20 / 否则 0
  在架时长 15  上架天数 / 30，满 30 天得满分
  质保条款 15  ≥30 天 15，≥25 天 12，≥14 天 8，≥7 天 5，其余 2
  稳定性   15  近 14 天自动核价通过的比例（不足 3 次按一半计）
  投诉     25  近 90 天每条未解决的投诉 −10，已解决 −3
Listings enter the public top-N only with a passing price check and a score of at least 50.
"""
import datetime as dt, gzip, html, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "merchants")
API = os.environ.get("BBWITH_API", "https://bbwith.com/api/listings")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
OUT_OF_STOCK = re.compile(r"缺货|售罄|已售完|库存不足|暂无库存|商品已下架|库存\s*[:：]\s*0(?!\d)|sold out|out of stock", re.I)


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*",
                                               "Accept-Language": "zh-CN,zh;q=0.9", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        return b.decode("utf8", "replace")


def price_on_page(page, price):
    """True if the declared price shows up as a number on the page (text or embedded JSON)."""
    want = f"{price:.2f}".rstrip("0").rstrip(".")
    for m in re.finditer(r"(?<![\d.])(\d{1,6}(?:\.\d{1,2})?)(?![\d.])", page):
        v = m.group(1)
        if v.rstrip("0").rstrip(".") == want if "." in v else v == want:
            return True
    return False


def check(listing):
    try:
        page = fetch(listing["url"])
    except Exception as e:
        return {"ok": False, "why": f"打不开（{type(e).__name__}）"}
    text = html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", page, flags=re.S))
    if not price_on_page(page, listing["price"]):
        return {"ok": False, "why": "页面上没找到申报的价格"}
    if OUT_OF_STOCK.search(text) and not re.search(r"库存\s*[:：]\s*[1-9]", text):
        return {"ok": False, "why": "页面显示缺货"}
    return {"ok": True, "why": ""}


def parse_t(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def score(l, hist, complaints, now):
    parts = {}
    last = hist[-1] if hist else None
    manual = parse_t(l.get("manual_verified_at"))
    if last and last["ok"] and now - parse_t(last["t"]) < dt.timedelta(hours=30):
        parts["verify"] = 30
    elif manual and now - manual < dt.timedelta(days=7):
        parts["verify"] = 20
    else:
        parts["verify"] = 0
    since = parse_t(l.get("approved_at") or l["created_at"])
    parts["age"] = round(min((now - since).days / 30, 1) * 15, 1)
    w = l["warranty_days"]
    parts["warranty"] = 15 if w >= 30 else 12 if w >= 25 else 8 if w >= 14 else 5 if w >= 7 else 2
    recent = [h for h in hist if now - parse_t(h["t"]) < dt.timedelta(days=14)]
    parts["stable"] = round(15 * sum(h["ok"] for h in recent) / len(recent), 1) if len(recent) >= 3 else 7.5
    pen = 0
    for c in complaints:
        if c["merchant_id"] == l["merchant_id"] and now - parse_t(c["published_at"]) < dt.timedelta(days=90):
            pen += 3 if c["resolved"] else 10
    parts["complaints"] = max(0, 25 - pen)
    return round(sum(parts.values())), parts


def main():
    data = json.loads(fetch(API))
    os.makedirs(DIR, exist_ok=True)
    hpath = os.path.join(DIR, "history.json")
    history = json.load(open(hpath)) if os.path.exists(hpath) else {}
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for l in data["listings"]:
        key = str(l["id"])
        r = check(l)
        h = history.setdefault(key, [])
        h.append({"t": stamp, "ok": r["ok"], "price": l["price"], "why": r["why"]})
        del h[:-60]
        s, parts = score(l, h, data["complaints"], now)
        out.append({**l, "check": h[-1], "score": s, "parts": parts,
                    "eligible": parts["verify"] > 0 and s >= 50})
        print(f"#{l['id']} {l['merchant']} {l['plan_key']} ¥{l['price']}: {'ok' if r['ok'] else r['why']} score {s}")
        time.sleep(1)
    live = {str(l["id"]) for l in data["listings"]}
    history = {k: v for k, v in history.items() if k in live}
    json.dump(history, open(hpath, "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump({"time": stamp, "listings": out, "complaints": data["complaints"]},
              open(os.path.join(DIR, "latest.json"), "w"), ensure_ascii=False, indent=0)
    print(f"{len(out)} listings checked, {sum(x['eligible'] for x in out)} eligible")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        assert price_on_page("售价 ¥108.00 元", 108) and price_on_page('"price":108.5,', 108.5)
        assert not price_on_page("¥1108", 108) and not price_on_page("108.5", 108)
        print("ok")
        sys.exit()
    main()

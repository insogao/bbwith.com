"""Collect App Store gift card prices from public retailer pages (run in GitHub Actions).

Retailers: Bitrefill, SEAGM, Eneba. For each card we keep the face value (local currency),
the price in USD and a /go/ slug for the outbound link. Output: data/giftcards/<date>.json
"""
import datetime as dt, gzip, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# region -> (currency, retailer pages). Only App Store regions where AI plans are cheap, plus US/JP.
REGIONS = {
    "tr": ("TRY", {"bitrefill": "itunes-turkey", "seagm": "itunes-gift-card-turkey",
                   "eneba": ["apple-apple-gift-card-{n}-try-key-turkey", [100, 200, 250, 400, 500, 600, 1000]]}),
    "id": ("IDR", {"bitrefill": "apple-itunes-indonesia", "seagm": "itunes-gift-card-indonesia"}),
    "br": ("BRL", {"bitrefill": "app-store-and-itunes-brazil", "seagm": "itunes-gift-card-brazil"}),
    "in": ("INR", {"bitrefill": "app-store-and-itunes-inr-india", "seagm": "itunes-gift-card-india"}),
    "jp": ("JPY", {"bitrefill": "itunes-japan", "seagm": "itunes-gift-card-japan"}),
    "us": ("USD", {"bitrefill": "itunes-usa", "seagm": "itunes-gift-card-united-states"}),
}
RETAILERS = {
    "bitrefill": {"name": "Bitrefill", "pay": "加密货币（BTC/USDT 等）", "url": "https://www.bitrefill.com/us/en/gift-cards/{slug}/"},
    "seagm": {"name": "SEAGM", "pay": "信用卡、PayPal、支付宝等", "url": "https://www.seagm.com/{slug}"},
    "eneba": {"name": "Eneba", "pay": "信用卡、PayPal 等（第三方卖家）", "url": "https://www.eneba.com/{slug}"},
}


def get(url):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8",
                                                       "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return b.decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(3 * (attempt + 1))
    print(f"  failed {url}: {last!r}")
    return None


def json_at(s, i):
    """Parse the JSON array/object that starts at s[i]."""
    depth, j, ins, esc = 0, i, False, False
    while j < len(s):
        c = s[j]
        if ins:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                ins = False
        elif c == '"':
            ins = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return json.loads(s[i:j + 1])
        if c != "\\":
            esc = False if not ins else esc
        j += 1
    raise ValueError("unterminated JSON")


def parse_bitrefill(html):
    """{face: usd}. Pages carry two package lists: one with usdPrice/prices, one priced in USD cents."""
    best = {}
    for m in re.finditer(r'"packages":\[', html):
        try:
            arr = json_at(html, m.end() - 1)
        except ValueError:
            continue
        tail = html[m.end():m.end() + 6000]
        got = {}
        for p in arr:
            if not isinstance(p, dict) or "value" not in p:
                continue
            face = float(p["value"])
            if p.get("usdPrice"):
                got[face] = float(p["usdPrice"])
            elif isinstance(p.get("prices"), dict) and p["prices"].get("USD"):
                got[face] = p["prices"]["USD"] / 100
            elif "price" in p and '"paymentCurrency":"USD"' in tail[:3000]:
                got[face] = p["price"] / 100
        for k, v in got.items():
            best.setdefault(k, v)
    return {k: round(v, 2) for k, v in best.items() if v > 0}


def parse_seagm(html):
    m = re.search(r"prodectBuyList:\s*\[", html)
    if not m:
        return {}
    out = {}
    for a in json_at(html, m.end() - 1):
        if a.get("item_variant") != "Available":
            continue
        n = re.search(r"([\d][\d,\.]*)\s*(TL|TRY|IDR|BRL|INR|Yen|JPY|USD)\b", a["item_name"])
        if not n:
            continue
        face = float(n.group(1).replace(",", ""))
        out[face] = round(float(a["price"]) - float(a.get("discount") or 0), 2)
    return out


def parse_eneba(html):
    """Cheapest in-stock offer in USD on a single-denomination product page."""
    prices = [int(m.group(1)) / 100 for m in re.finditer(
        r'"price\(\{\\"currency\\":\\"USD\\"\}\)":\{"__typename":"Money","amount":(\d+),"currency":"USD"\},'
        r'"promotionalPrice\(\{\\"currency\\":\\"USD\\"\}\)":(?:null|\{[^}]*\}),"isInStock":true', html)]
    return min(prices) if prices else None


def collect():
    items = []
    for cc, (cur, shops) in REGIONS.items():
        for shop, spec in shops.items():
            if shop == "eneba":
                tpl, faces = spec
                for n in faces:
                    slug = tpl.format(n=n)
                    html = get(RETAILERS[shop]["url"].format(slug=slug))
                    usd = parse_eneba(html) if html else None
                    if usd:
                        items.append({"shop": shop, "cc": cc, "cur": cur, "face": float(n), "usd": usd, "slug": slug})
                    time.sleep(1)
                continue
            html = get(RETAILERS[shop]["url"].format(slug=spec))
            got = (parse_bitrefill if shop == "bitrefill" else parse_seagm)(html) if html else {}
            print(f"{cc} {shop}: {len(got)} denominations")
            for face, usd in sorted(got.items()):
                items.append({"shop": shop, "cc": cc, "cur": cur, "face": face, "usd": usd, "slug": spec})
            time.sleep(1.5)
    return items


def selftest():
    d = "/tmp/probe/probe"
    if not os.path.isdir(d):
        return
    print("bitrefill tr", sorted(parse_bitrefill(open(f"{d}/00.html").read()).items())[:6])
    print("bitrefill jp", sorted(parse_bitrefill(open(f"{d}/04.html").read()).items())[:6])
    print("bitrefill us", sorted(parse_bitrefill(open(f"{d}/05.html").read()).items())[:6])
    print("seagm tr", sorted(parse_seagm(open(f"{d}/09.html").read()).items())[:8])
    print("eneba tr500", parse_eneba(open(f"{d}/17.html").read()))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit()
    items = collect()
    if len(items) < 20:
        sys.exit(f"only {len(items)} gift card prices collected; not writing")
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    os.makedirs(os.path.join(ROOT, "data", "giftcards"), exist_ok=True)
    path = os.path.join(ROOT, "data", "giftcards", f"{now.date().isoformat()}.json")
    json.dump({"date": now.date().isoformat(), "time": now.strftime("%Y-%m-%d %H:%M"), "items": items},
              open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(items)} prices to {path}")

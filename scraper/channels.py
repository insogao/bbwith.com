"""Collect domestic top-up (代充) prices from the 16688 source plaza and aggregate them per plan.

Credentials come from environment variables (set them as GitHub Actions secrets):
  S16688_TOKEN        the "value" field of localStorage["merchant-token"]
  S16688_DEVICE_KEY   localStorage["merchant-device-key"]
  S16688_VISITOR_KEY  localStorage["visitor-id"]

Only aggregates are written (data/channels/<date>.json): per plan and delivery type (代充, 成品号,
Team 车位, 拼车, 优惠渠道) the count, lowest, 25th percentile and median price; top-ups are also split
by the payment route sellers name (菲区, 美区 iOS ...).
No seller names, product names or links are stored.

python scraper/channels.py            # fetch and write
python scraper/channels.py --selftest # run the classifier tests only
"""
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = "https://www.16688.com.cn/merchantApi/SourceGoods/list"
# The platform hides some brand words, so search with the forms sellers actually use.
KEYWORDS = ["Plus", "Pro", "Go", "Codex", "Team", "Claude", "Max", "Gemini", "Google", "Ultra", "Gro", "Gork", "Cursor"]

# ---------- classification ----------
# Model: a listing is (product, plan, type). "type" is how it is delivered:
#   topup   代充 / 直充 / CDK, the subscription is paid on your own account
#   account 成品号, a ready-made account (split by warranty: long >= 25 days, short)
#   seat    Team / Business seat (车位 / 席位)
#   shared  拼车 / 共享 / 镜像
#   promo   半价、学生、活动链接等优惠渠道 (duration and eligibility vary)
# Listings that are not a subscription at all (资格号, 教程, 退款, 接码 ...) are dropped.

SKIP = re.compile(r"资格|教程|自助退款|退款服务|pro退款|换绑邮箱|号池|反代专用|仅反代|api对接|接码|静态ip|住宅ip|流量|capcut|office|minimax|"
                  r"youtube|netflix|spotify|kiro|windsurf|suno|perplexity|推特|蓝v|盲盒", re.I)
ANNUAL = re.compile(r"年卡|一年|1年|12个月|十二个月|360天|365天|年费", re.I)
SHORT_TERM = re.compile(r"周卡|周抛|(?<!\d)7天|七天|日抛|天卡|日卡", re.I)
# Seller says in the title that delivery or after-sales is not covered. Such listings undercut honest ones,
# so they are counted but left out of the price summary (see aggregate()).
NO_GUARANTEE = re.compile(r"不包到账|不保到账|不保证到账|可能不到账|有概率不到账|秒封不保|封号不保|不包售后|无售后|不售后|概不售后|拍下不退|不退不换.{0,4}不售后", re.I)
UPGRADE_NOTE = re.compile(r"(可|支持|自助)?(补差价?)?(升级|补差)[^，,｜|【】（）()\[\]]*")

PRODUCT_RX = [
    ("claude", r"claude|克劳德"),
    ("google-ai", r"gemini|google\s*ai|谷歌\s*ai|antigravity|反重力"),
    ("grok", r"g\W?r\W?o\W?k|gork|\bgro\b|gro[\.。/]|gr0k|格洛克|基rok|supergrok"),
    ("cursor", r"cursor"),
    ("chatgpt", r"g\W*p\W*t|g\W*t\W*p|jpt|鸡\W*p|🐔pt|chat|codex|openai|g\s*plus|g\s*pro|\bgp\b|g\W*pp|(?<![a-z])(plus|pro|go|team|business)(?![a-z])|go会员"),
]

TYPE_RX = [
    ("shared", r"拼车|共享|合租|镜像|三人|多人|共用"),
    ("seat", r"team|business|车位|席位|母号|邀请"),
    ("promo", r"半价|学生|教育|大兵|优惠|激活链接|兑换链接|开通链接|活动|\d+个月会员|[3-9]个月|三个月|六个月|两个月"),
    ("account", r"成品"),
    ("topup", r"代充|直充|直冲|官充|官冲|官方充值|卡充|卡冲|cdk|卡密|充值|充自己|礼品卡|兑换码"),
    ("account", r"独享|账号|日抛|周限|实卡|极品号|已接马|未接马|接马"),
    ("topup", r"月卡|ios渠道|官方"),
]

ROUTES = [  # (route key, label, pattern) for top-ups
    ("ph", "菲区卡充", r"菲区|菲律宾|菲"),
    ("us-ios", "美区 iOS", r"美区|美国|ios"),
    ("eg", "埃及卡充", r"埃及|埃区"),
    ("cl", "智利卡充", r"智利"),
    ("jp", "日区", r"日区|日本"),
    ("tr", "土区", r"土区|土耳其"),
]


def plan_of(product, n):
    has = lambda rx: re.search(rx, n, re.I)
    if product == "chatgpt":
        if has(r"team|business|车位|席位"):
            return "team"
        if has(r"pro\s*500|500\s*(刀|\$|💲|美元|美金)|50x|25x|pro\s*max"):
            return "pro-500"
        if has(r"pro\s*200|200\s*(刀|\$|💲|美元|美金)|20x") and not has(r"pro\s*100"):
            return "pro-200"
        if has(r"pro\s*100|100\s*(刀|\$|💲|美元|美金)|5x|10x"):
            return "pro-100"
        if has(r"\bgo\b|go会员|go埃区") and not has(r"gopay"):
            return "go"
        if has(r"plus") and not has(r"\bpro\b|pro\d"):
            return "plus"
        return None
    if product == "claude":
        if has(r"team"):
            return "team"
        if has(r"20x|200\s*(刀|\$|美元)|max\s*20"):
            return "max-20x"
        if has(r"max|5x|100\s*(刀|\$|美元)"):
            return "max-5x"
        if has(r"pro"):
            return "pro"
        return None
    if product == "google-ai":
        if has(r"ultra"):
            return "ultra"
        if has(r"pro"):
            return "pro"
        if has(r"plus"):
            return "plus"
        return None
    if product == "grok":
        if has(r"heavy|300\s*(刀|\$|美元)"):
            return "supergrok-heavy"
        if has(r"super|premium|30\s*(刀|\$|美元)"):
            return "supergrok"
        if has(r"plus|8\s*(刀|\$|美元|美金)"):
            return "plus"
        return None
    if product == "cursor":
        if has(r"ultra"):
            return "ultra"
        if has(r"pro\s*\+|pro\s*plus|60\s*(刀|\$)"):
            return "pro-plus"
        if has(r"pro"):
            return "pro"
        return None
    return None


def warranty_days(n):
    m = re.search(r"(?:质保|保)\s*(?:订阅|封号|首登和)?\s*(\d{1,3})\s*天", n)
    if m:
        return int(m.group(1))
    if re.search(r"质保(一|1)个月|一个月订阅|保订阅一个月|质保订阅一个月|质保一月", n):
        return 30
    if re.search(r"首登|质保\s*\d+\s*(小时|分钟)|保\s*\d+\s*小时", n):
        return 0
    return None


def route_of(n):
    for key, _, rx in ROUTES:
        if re.search(rx, n, re.I):
            return key
    return "other"


def classify(name):
    """Return dict(product, plan, type, route, warranty) for a subscription listing, else None."""
    n = name.replace("Ｇ", "G").replace("Ｐ", "P").replace("Ｔ", "T")
    if SKIP.search(n) or "非克劳德" in n and re.search(r"claude|克劳德", n.replace("非克劳德", ""), re.I) is None and not re.search(r"pro|plus", n, re.I):
        return None
    n = UPGRADE_NOTE.sub(" ", n).replace("非克劳德", "")
    product = next((p for p, rx in PRODUCT_RX if re.search(rx, n, re.I)), None)
    if not product:
        return None
    plan = plan_of(product, n)
    if not plan:
        return None
    typ = next((t for t, rx in TYPE_RX if re.search(rx, n, re.I)), None)
    if not typ:
        return None
    if plan == "team":
        typ = "seat"
    if typ != "promo" and (ANNUAL.search(n) or SHORT_TERM.search(n) and typ == "topup"):
        return None  # only monthly top-ups and accounts are comparable
    w = warranty_days(n)
    if typ == "account":
        typ = "account-long" if (w or 0) >= 25 else "account-short"
    return {"product": product, "plan": plan, "type": typ, "route": route_of(n) if typ == "topup" else None, "warranty": w}


def _c(name):
    c = classify(name)
    return None if c is None else (c["product"], c["plan"], c["type"], c["route"])


SELFTEST = [
    ("【菲区卡充】G Plus 20刀 官充 月卡 【质保订阅30天】", ("chatgpt", "plus", "topup", "ph")),
    ("【IOS美区】G Plus 官充 年卡【质保订阅360天】", None),
    ("J*PT Codex Plus【IOS美区】官方充值 质保30天 有账单", ("chatgpt", "plus", "topup", "us-ios")),
    ("🔥🔥🔥【开票快，支持续费】GP,T Codex Pro200充值套餐【Pro20x】【质保订阅30天】【官方直充】【充值到自己的号】【一卡一绑】plus", ("chatgpt", "pro-200", "topup", "other")),
    ("🔥🔥🔥【开票快，支持续费】GP,T Codex Pro100 充值套餐【Pro5x】【质保订阅30天】【官方直充】【充值到自己的号】【带官方账单】plus", ("chatgpt", "pro-100", "topup", "other")),
    ("GP,T Codex 【半价Plus】充值套餐 账号有半价优惠资格才能充！【质保订阅30天】", None),
    ("GP,T菲区半价实付代充 Plus月卡 菲区卡充 有官方账单 质保30天 可开发票", ("chatgpt", "plus", "promo", None)),
    ("【Plus成品号】UPI未接马 保1小时 张密2FA 11.20 产", ("chatgpt", "plus", "account-short", None)),
    ("最稳渠道质保30天Plus越南实卡｜gmail邮箱独享成品号", ("chatgpt", "plus", "account-long", None)),
    ("🔥【官网正价直充】GO会员【官方直充】✅【质保订阅30天】✅【售后同步官方】【带官方账单】", ("chatgpt", "go", "topup", "other")),
    ("【官方充值】Gro。k Plus 美区 卡充CDK 一个月（质保订阅）", ("grok", "plus", "topup", "us-ios")),
    ("【IOS美】G Pro 5x 100刀会员 官充 月卡【质保订阅30天】", ("chatgpt", "pro-100", "topup", "us-ios")),
    ("【美区IOS】JPT Codex Pro 50X官方充值 质保30天【Pro50x】", ("chatgpt", "pro-500", "topup", "us-ios")),
    ("【埃及卡充】G Pro 5x 100刀会员 官充 月卡【质保订阅30天】", ("chatgpt", "pro-100", "topup", "eg")),
    ("Claude Pro直充月卡 (IOS渠道需要强制KYC，介意勿下)", ("claude", "pro", "topup", "us-ios")),
    ("【美区IOS】Pro 5X 官方充值 质保30天订阅 （直充自己号）非克劳德", ("chatgpt", "pro-100", "topup", "us-ios")),
    ("Claude Pro【独享成品号】｜质保订阅｜封号不保（免K成品）", ("claude", "pro", "account-short", None)),
    ("Gemini plus 6个月激活链接（非成品号，无需绑卡，直接激活）", ("google-ai", "plus", "promo", None)),
    ("【IOS渠道】Gemini Google AI Pro 20刀 月卡【质保订阅30天】", ("google-ai", "pro", "topup", "us-ios")),
    ("plus拼车【三人拼】", ("chatgpt", "plus", "shared", None)),
    ("Codex Team 月权益【车位】（正规车位）【可与plus并存，缓解额度不够用问题】（质保订阅 30 天）", ("chatgpt", "team", "seat", None)),
    ("【官方充值】埃及区G.TP Pro500 cdk24小时（质保30天）正规充值", ("chatgpt", "pro-500", "topup", "eg")),
    ("🔥🔥【官网直充自己号】菲区 Plus 1个月｜ 质保30天售后同步官方｜带官方发票账单｜24H全自动秒充｜支持补差升级到5x 20x", ("chatgpt", "plus", "topup", "ph")),
    ("Codex Pro 5X 【保订阅~埃及/智利卡冲】支持续费（不支持升级菲区20x）", ("chatgpt", "pro-100", "topup", "eg")),
    ("🔥【IOS美区】GP,T plus 1年官方正规充值 可以开发票（付款后秒发CDK直充自己号）", None),
    ("Claude Pro 专属独享号池【单号独享IP·防封号环境部署·800-1100刀额度·已过KYC", None),
    ("ic邮箱plus半价资格号，不是成品是资格号,试用1-3个月随机(不是 成品Plus!!!)", None),
    ("🔥【官网正价直充】GO会员【官方直充】✅【质保订阅30天】✅【售后同步官方】【带官方账单】【正规卡充值】🟢【可开票】Codex支持未用卡密退款plus", ("chatgpt", "go", "topup", "other")),
    ("Plus独享账号|· 家宽手搓 |· 未接马|· 账密+2FA· 质保首登· 诚招代理", ("chatgpt", "plus", "account-short", None)),
    ("【日本实卡plus可升级5x】PLUS 未接马 iCloud邮箱 可反代可网页（质保30天）", ("chatgpt", "plus", "account-long", None)),
    ("🔥plus极品号--店家甄选(15天双质保）已接马", ("chatgpt", "plus", "account-short", None)),
    ("G*P codex plus pro退款 自助退款 不成功不收费", None),
    ("普通区（非美欧新日等发达地区）成品过kyc，claude Ultra(max20x)", ("claude", "max-20x", "account-short", None)),
    ("质保到账-Claude Max 100刀 礼品卡", ("claude", "max-5x", "topup", None) if False else ("claude", "max-5x", "topup", "other")),
    ("Cursor pro+ 成品号 60刀+auto 1200刀 质保订阅", ("cursor", "pro-plus", "account-short", None)),
    ("【GGbond】gro/k plus（8$） 代充 【质保一个月订阅】", ("grok", "plus", "topup", "other")),
    ("Codex Team 周卡【车位x1】标准席位【可与plus并存，缓解额度不够用问题】（质保订阅7天）", ("chatgpt", "team", "seat", None)),
]


def selftest():
    bad = [(n, want, _c(n)) for n, want in SELFTEST if _c(n) != want]
    for n, want, got in bad:
        print("FAIL", got, "!=", want, "|", n[:60])
    print(f"{len(SELFTEST) - len(bad)}/{len(SELFTEST)} ok")
    return not bad


# ---------- fetch ----------

def fetch_all():
    tok, dev, vis = (os.environ.get(k, "") for k in ("S16688_TOKEN", "S16688_DEVICE_KEY", "S16688_VISITOR_KEY"))
    if not tok:
        sys.exit("S16688_TOKEN is not set; skipping")
    headers = {"Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
               "Merchant-Token": tok, "device-key": dev, "visitor-key": vis, "visitor_key": vis,
               "Origin": "https://www.16688.com.cn", "Referer": "https://www.16688.com.cn/merchant/source",
               "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
    page_size = 20  # small pages: long responses from GitHub's US runners to China often get cut off

    def post(kw, page):
        body = json.dumps({"page_no": page, "page_size": page_size, "source_category_id": 0, "keywords": kw,
                           "merchant_no": "", "sort": "composite"}).encode()
        last = None
        for attempt in range(5):
            try:
                req = urllib.request.Request(API, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=40) as r:
                    return json.loads(r.read())
            except Exception as e:  # IncompleteRead, timeouts, resets
                last = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"16688 request failed for {kw!r} page {page}: {last!r}")

    items, failed = {}, []
    for kw in KEYWORDS:
        for page in range(1, 51):
            try:
                j = post(kw, page)
            except RuntimeError as e:
                print(e)
                failed.append(kw)
                break
            if j.get("code") != 1:
                msg = j.get("msg") or ""
                write_status(False, "16688 登录已过期，需要更新 S16688_TOKEN" if "登录" in msg else f"16688 接口出错：{msg}"[:80])
                sys.exit(f"16688 API error for {kw!r}: {msg}")
            for g in j["data"]["list"]:
                items[g["id"]] = g
            if len(j["data"]["list"]) < page_size:
                break
            time.sleep(0.8)
        time.sleep(1.2)
    if failed:
        print("keywords with errors:", failed)
    if len(items) < 300:
        sys.exit(f"only {len(items)} listings fetched; not writing data")
    return list(items.values())


def aggregate(items):
    """plans[product/plan][type] = {count, min, p25, median, sales[, routes]}; low outliers trimmed."""
    groups, risky = {}, {}
    for g in items:
        if g.get("status", 1) != 1:
            continue
        c = classify(g.get("name", ""))
        price = float(g.get("price") or 0)
        if not c or price <= 0:
            continue
        key = f'{c["product"]}/{c["plan"]}'
        if NO_GUARANTEE.search(g.get("name", "")):
            risky.setdefault(key, {}).setdefault(c["type"], 0)
            risky[key][c["type"]] += 1
            continue
        groups.setdefault(key, {}).setdefault(c["type"], []).append((price, c["route"], int(g.get("sales_count") or 0)))

    def summ(rows):
        ps = sorted(p for p, _, _ in rows)
        med = statistics.median(ps)
        kept = [r for r in rows if r[0] >= med * 0.3]  # drop 引流价 / mislabeled listings far below the median
        ps = sorted(p for p, _, _ in kept)
        return {"count": len(ps), "min": ps[0], "p25": ps[len(ps) // 4], "median": statistics.median(ps),
                "sales": sum(s for _, _, s in kept), "trimmed": len(rows) - len(kept)}

    out = {}
    for key, types in groups.items():
        out[key] = {}
        for typ, rows in types.items():
            d = summ(rows)
            if typ == "topup":
                routes = {}
                for r in rows:
                    routes.setdefault(r[1], []).append(r)
                d["routes"] = {k: summ(v) for k, v in routes.items()}
            d["no_guarantee"] = risky.get(key, {}).get(typ, 0)
            out[key][typ] = d
    return out


PICK_PLANS = ("chatgpt/go", "chatgpt/plus", "chatgpt/pro-100", "chatgpt/pro-200", "claude/pro", "claude/max-5x", "claude/max-20x",
              "google-ai/pro", "grok/supergrok")


def write_status(ok, why=""):
    """data/channels/status.json tells the site whether this feed is healthy (shown next to its update clock)."""
    p = os.path.join(ROOT, "data", "channels", "status.json")
    prev = json.load(open(p)) if os.path.exists(p) else {}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    st = {"ok": ok, "why": why, "checked": now,
          "since": prev.get("since") if (prev.get("ok") == ok and prev.get("since")) else now}
    json.dump(st, open(p, "w"), ensure_ascii=False)


def write_candidates(items, when):
    """Cheapest trustworthy-looking 代充 listings per plan, for scraper/shoppick.py to choose from.
    Only fields needed to look a product up on its public page are kept."""
    by = {}
    for g in items:
        if g.get("status", 1) != 1:
            continue
        name = g.get("name", "")
        c = classify(name)
        if not c or c["type"] != "topup" or NO_GUARANTEE.search(name):
            continue
        key = f'{c["product"]}/{c["plan"]}'
        if key not in PICK_PLANS:
            continue
        keep = {k: v for k, v in g.items() if re.search(r"no$|_no|id$|name|price|sales|stock|shop|merchant", k, re.I) and not isinstance(v, (dict, list))}
        by.setdefault(key, []).append(keep)
    out = {}
    for key, rows in by.items():
        rows.sort(key=lambda r: float(r.get("price") or 1e9))
        med = statistics.median(float(r.get("price") or 0) for r in rows)
        out[key] = [r for r in rows if float(r.get("price") or 0) >= med * 0.3][:25]
    json.dump({"time": when, "plans": out}, open(os.path.join(ROOT, "data", "channels", "candidates.json"), "w", encoding="utf8"),
              ensure_ascii=False, indent=0)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if not selftest():
        sys.exit("classifier self-test failed")
    items = fetch_all()
    plans = aggregate(items)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    fx = json.load(urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=20))
    out = {"date": now.date().isoformat(), "time": now.isoformat(timespec="minutes"), "source": "16688",
           "currency": "CNY", "usd_cny": fx["rates"]["CNY"], "listings_seen": len(items), "plans": plans}
    os.makedirs(os.path.join(ROOT, "data", "channels"), exist_ok=True)
    write_candidates(items, out["time"])
    write_status(True)
    path = os.path.join(ROOT, "data", "channels", f"{out['date']}.json")
    json.dump(out, open(path, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(len(items), "listings")
    for k, types in sorted(plans.items()):
        print(" ", k, ", ".join(f"{t}: {v['count']}@¥{v['min']}/¥{v['median']}" for t, v in sorted(types.items())))


if __name__ == "__main__":
    main()

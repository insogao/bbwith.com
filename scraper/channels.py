"""Collect domestic top-up (代充) prices from the 16688 source plaza and aggregate them per plan.

Credentials come from environment variables (set them as GitHub Actions secrets):
  S16688_TOKEN        the "value" field of localStorage["merchant-token"]
  S16688_DEVICE_KEY   localStorage["merchant-device-key"]
  S16688_VISITOR_KEY  localStorage["visitor-id"]

Only aggregates are written (data/channels/<date>.json): per plan the lowest, median and count of
monthly top-up listings, split by the payment route sellers name (菲区, 美区 iOS ...).
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
KEYWORDS = ["Plus", "Pro", "Go", "Codex", "Claude"]

# ---------- classification ----------

EXCLUDE = re.compile(
    r"成品|资格|半价|试用|0元|镜像|拼车|共享|合租|车位|席位|team|business|周卡|周限|日抛|年卡|一年|12个月|"
    r"6个月|3个月|1年|号池|三个月|两个月|360天|教程|退款|接马|反代|邮箱|gemini|capcut|office|minimax|cursor|"
    r"g\.?r\.?o\.?k|gork|gro\b|gro\.|格洛克|基rok|superg|perplexity|youtube|netflix|spotify|代理|批发价|1x|2x|4x",
    re.I)
TOPUP = re.compile(r"代充|直充|直冲|官充|官冲|官方充值|正价|卡充|卡冲|cdk|卡密|充值|充自己|ios", re.I)
GPT = re.compile(r"g\W*p\W*t|g\W*t\W*p|jpt|鸡\W*p|🐔pt|chat|codex|openai|g\s*plus|g\s*pro|\bgp\b|g\W*pp|go会员", re.I)

ROUTES = [  # (route key, label, pattern)
    ("ph", "菲区卡充", r"菲区|菲律宾|菲"),
    ("us-ios", "美区 iOS", r"美区|美国|ios"),
    ("eg", "埃及卡充", r"埃及|埃区"),
    ("cl", "智利卡充", r"智利"),
    ("jp", "日区", r"日区|日本"),
    ("tr", "土区", r"土区|土耳其"),
]


UPGRADE_NOTE = re.compile(r"[^，,｜|【】（）()\[\]]*(升级|补差)[^，,｜|【】（）()\[\]]*")


def chatgpt_plan(n):
    n = UPGRADE_NOTE.sub(" ", n)  # "支持补差升级到5x 20x" describes an upgrade, not this plan
    if re.search(r"pro\s*500|500\s*(刀|\$|💲|美元|美金)|pro\s*50x|50x|25x|pro\s*max", n, re.I):
        return "pro-500"
    if re.search(r"pro\s*200|200\s*(刀|\$|💲|美元|美金)|20x|pro\s*10x(?!.*pro100)", n, re.I) and not re.search(r"pro\s*100", n, re.I):
        return "pro-200"
    if re.search(r"pro\s*100|100\s*(刀|\$|💲|美元|美金)|5x|10x", n, re.I):
        return "pro-100"
    if re.search(r"\bgo\b|go会员", n, re.I) and not re.search(r"gopay", n, re.I):
        return "go"
    if re.search(r"plus", n, re.I) and not re.search(r"\bpro\b|pro\d", n, re.I):
        return "plus"
    return None


def classify(name):
    """Return (product, plan, route) for a monthly top-up listing, else None."""
    n = name.replace("Ｇ", "G").replace("Ｐ", "P").replace("Ｔ", "T")
    if EXCLUDE.search(n) or not TOPUP.search(n):
        return None
    n = UPGRADE_NOTE.sub(" ", n)
    if re.search(r"gemini|google|youtube|推特|twitter|\bx\s*premium|蓝v", n, re.I):
        return None
    if re.search(r"claude|克劳德", n, re.I):
        if "非克劳德" in n:
            return None
        if re.search(r"claude\s*pro", n, re.I) and not re.search(r"max|5x|20x", n, re.I):
            return ("claude", "pro", route_of(n))
        return None
    # Other brands are excluded above, so a bare "Plus"/"Pro"/"Go" top-up is ChatGPT.
    if not GPT.search(n) and not re.search(r"\b(plus|pro|go)\b", n, re.I):
        return None
    plan = chatgpt_plan(n)
    return ("chatgpt", plan, route_of(n)) if plan else None


def route_of(n):
    for key, _, rx in ROUTES:
        if re.search(rx, n, re.I):
            return key
    return "other"


SELFTEST = [
    ("【菲区卡充】G Plus 20刀 官充 月卡 【质保订阅30天】", ("chatgpt", "plus", "ph")),
    ("【IOS美区】G Plus 官充 年卡【质保订阅360天】", None),
    ("J*PT Codex Plus【IOS美区】官方充值 质保30天 有账单", ("chatgpt", "plus", "us-ios")),
    ("🔥🔥🔥【开票快，支持续费】GP,T Codex Pro200充值套餐【Pro20x】【质保订阅30天】【官方直充】【充值到自己的号】【一卡一绑】【未使用卡密支持销毁售后】plus", ("chatgpt", "pro-200", "other")),
    ("🔥🔥🔥【开票快，支持续费】GP,T Codex Pro100 充值套餐【Pro5x】【质保订阅30天】【官方直充】【充值到自己的号】【带官方账单】【未使用卡密支持销毁售后】plus", ("chatgpt", "pro-100", "other")),
    ("GP,T Codex 【半价Plus】充值套餐 账号有半价优惠资格才能充！【质保订阅30天】", None),
    ("【Plus成品号】UPI未接马 保1小时 张密2FA 11.20 产", None),
    ("🔥【官网正价直充】GO会员【官方直充】✅【质保订阅30天】✅【售后同步官方】【带官方账单】", ("chatgpt", "go", "other")),
    ("【官方充值】Gro。k Plus 美区 卡充CDK 一个月（质保订阅）", None),
    ("【IOS美】G Pro 5x 100刀会员 官充 月卡【质保订阅30天】", ("chatgpt", "pro-100", "us-ios")),
    ("【美区IOS】JPT Codex Pro 50X官方充值 质保30天【Pro50x】", ("chatgpt", "pro-500", "us-ios")),
    ("【埃及卡充】G Pro 5x 100刀会员 官充 月卡【质保订阅30天】", ("chatgpt", "pro-100", "eg")),
    ("Claude Pro直充月卡 (IOS渠道需要强制KYC，介意勿下)", ("claude", "pro", "us-ios")),
    ("【美区IOS】Pro 5X 官方充值 质保30天订阅 （直充自己号）非克劳德", None),
    ("Claude Pro【独享成品号】｜质保订阅｜封号不保（免K成品）", None),
    ("Gemini plus 6个月激活链接（非成品号，无需绑卡，直接激活）", None),
    ("【IOS渠道】Gemini Google AI Pro 20刀 月卡【质保订阅30天】", None),
    ("plus拼车【三人拼】", None),
    ("Codex Team 月权益【车位】（正规车位）【可与plus并存，缓解额度不够用问题】", None),
    ("【官方充值】埃及区G.TP Pro500 cdk24小时（质保30天）正规充值", ("chatgpt", "pro-500", "eg")),
    ("🔥🔥【官网直充自己号】菲区 Plus 1个月｜ 质保30天售后同步官方｜带官方发票账单｜24H全自动秒充｜支持补差升级到5x 20x", ("chatgpt", "plus", "ph")),
    ("Codex Pro 5X 【保订阅~埃及/智利卡冲】支持续费（不支持升级菲区20x）", ("chatgpt", "pro-100", "eg")),
    ("🔥【IOS美区】GP,T plus 1年官方正规充值 可以开发票（付款后秒发CDK直充自己号）", None),
    ("Claude Pro 专属独享号池【单号独享IP·防封号环境部署·800-1100刀额度·已过KYC", None),
]


def selftest():
    bad = [(n, want, classify(n)) for n, want in SELFTEST if classify(n) != want]
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
    items = {}
    for kw in KEYWORDS:
        for page in range(1, 21):
            body = json.dumps({"page_no": page, "page_size": 50, "source_category_id": 0, "keywords": kw,
                               "merchant_no": "", "sort": "composite"}).encode()
            req = urllib.request.Request(API, data=body, headers=headers, method="POST")
            j = json.load(urllib.request.urlopen(req, timeout=30))
            if j.get("code") != 1:
                sys.exit(f"16688 API error for {kw!r}: {j.get('msg')}")
            for g in j["data"]["list"]:
                items[g["id"]] = g
            if len(j["data"]["list"]) < 50:
                break
            time.sleep(1.0)
        time.sleep(1.5)
    return list(items.values())


def aggregate(items):
    groups = {}
    for g in items:
        if g.get("status", 1) != 1:
            continue
        c = classify(g.get("name", ""))
        if not c:
            continue
        product, plan, route = c
        price = float(g.get("price") or 0)
        if price <= 0:
            continue
        groups.setdefault(f"{product}/{plan}", []).append((price, route, int(g.get("sales_count") or 0)))

    def summ(rows):
        ps = sorted(p for p, _, _ in rows)
        # trim obvious outliers: the cheapest 10% when there are many listings (often mislabeled)
        return {"count": len(ps), "min": ps[0], "p25": ps[len(ps) // 4], "median": statistics.median(ps),
                "sales": sum(s for _, _, s in rows)}

    out = {}
    for key, rows in groups.items():
        routes = {}
        for p, r, s in rows:
            routes.setdefault(r, []).append((p, r, s))
        out[key] = {**summ(rows), "routes": {r: summ(v) for r, v in routes.items()}}
    return out


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
    path = os.path.join(ROOT, "data", "channels", f"{out['date']}.json")
    json.dump(out, open(path, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"{len(items)} listings, " + ", ".join(f"{k}: {v['count']}@¥{v['min']}" for k, v in sorted(plans.items())))


if __name__ == "__main__":
    main()

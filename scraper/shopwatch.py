"""Monitor a hand-picked set of public card-shop products (data/merchants/watch.json).

Reads 16688's public storefront API (the same calls its product page makes, no login):
  goods/detail    title, price, stock, sales
  shop/detail     shop name, months on the platform, deposit, total buyers
  payment/list + payment/quotePrice   what the buyer actually pays, fee included

Writes
  data/merchants/shops.json          latest state of every watched product
  data/merchants/shops_history.json  {goods_no: [[iso time, total, in_stock 0/1], ...]}, last 45 days

python scraper/shopwatch.py
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIR = os.path.join(ROOT, "data", "merchants")
API = "https://www.16688.com.cn/shopApi/"
HEAD = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (compatible; bbwith.com price monitor; +https://bbwith.com/about/)"}
KEEP_DAYS = 45


def post(ep, body):
    req = urllib.request.Request(API + ep, data=json.dumps(body).encode(), headers=HEAD)
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.load(r)
    if d.get("code") != 1:
        raise RuntimeError(d.get("msg") or "api error")
    return d.get("data")


def warranty(title):
    m = re.search(r"质保\s*(订阅)?\s*(\d+)\s*天", title) or re.search(r"(\d+)\s*天\s*质保", title)
    if m:
        return f"质保 {m.group(m.lastindex)} 天"
    if re.search(r"质保订阅一个月|质保一个月", title):
        return "质保 30 天"
    if "同步官方售后" in title or "售后同步官方" in title:
        return "售后同步官方"
    if "质保" in title:
        return "质保订阅（天数未写明）"
    return "未写明质保"


# fine print in the product description that the title leaves out; (flag, patterns)
RISKS = [
    ("可能不到账", r"(有|存在)?(可能|概率|几率)(性)?(出现)?不到账|不包到账|不保证到账|不到账.{0,12}(不负责|自行|不退)"),
    ("不到账要自己找苹果退款", r"自行(申请)?退款|自己.{0,6}退款"),
    ("可能要过 KYC 身份验证", r"KYC|kyc|人脸|身份验证"),
    ("封号不赔", r"封号.{0,20}(不补|不退|不赔|不负责|概不负责|不保)|不包封号|封号不保"),
    ("新注册账号不建议充", r"新(注册的?)?(账)?号.{0,10}(不要|谨慎|不到账|别)|\d+月\d*号?(之)?后注册.{0,6}(不要|不充)"),
    ("会员到期后才能充", r"(会员|订阅)?(已)?到期(状态)?.{0,6}(才|再)|未到期.{0,10}(不|等)"),
    ("掉订阅不负责", r"掉订阅.{0,10}(不负责|不售后|不保)"),
]


def risk_flags(desc):
    t = re.sub(r"<[^>]+>", " ", desc or "")
    t = re.sub(r"&nbsp;|\s+", " ", t)
    return [name for name, pat in RISKS if re.search(pat, t)]


def check(item):
    g = item["goods_no"]
    d = post("goods/detail", {"goods_no": g})
    if not d:
        return {"goods_no": g, "ok": False, "why": "商品已下架或不存在"}
    s = post("shop/detail", {"shop_no": d["shop_no"]}) or {}
    m = s.get("merchant") or {}
    pays = (post("payment/list", {"shop_no": d["shop_no"], "goods_no": g}) or {}).get("list") or []
    total = d["price"]
    if pays:
        q = post("payment/quotePrice", {"shop_no": d["shop_no"], "goods_no": g, "quantity": 1, "channel_id": pays[0]["id"], "coupon_code": ""}) or {}
        total = q.get("total_amount") or total
    qty = d.get("stock_available_quantity")
    manual = qty == -1  # 人工发货: no stock count
    in_stock = manual or (qty or 0) > 0
    return {
        "goods_no": g, "ok": True, "plan": item["plan"], "type": item["type"], "added": item.get("added"),
        "shop_no": d["shop_no"], "shop": s.get("name") or d.get("shop_alias") or "",
        "title": d["name"], "price": d["price"], "total": round(float(total), 2),
        "stock": None if manual else qty, "manual": manual, "in_stock": in_stock,
        "sales": d.get("sales_count_text") or "", "shop_sales": m.get("sales_count_text") or "",
        "months": m.get("joined_months"), "deposit": m.get("deposit_money"), "region": m.get("region") or "",
        "pays": [p["paytype"]["code"] for p in pays], "warranty": warranty(d["name"]),
        "risks": risk_flags(d.get("description")),
        "url": f"https://www.16688.com.cn/goods/{g}",
    }


GRACE_HOURS = 12   # a read error keeps the last good reading this long (about 3 runs) before the row is hidden


def main():
    watch = json.load(open(os.path.join(DIR, "watch.json")))["items"]
    now_dt = dt.datetime.now(dt.timezone.utc)
    now = now_dt.isoformat(timespec="minutes")
    lp = os.path.join(DIR, "shops.json")
    last = {r["goods_no"]: r for r in (json.load(open(lp)).get("items", []) if os.path.exists(lp) else [])}
    out = []
    for it in watch:
        g, prev = it["goods_no"], last.get(it["goods_no"], {})
        try:
            r = check(it)
            r["checked"] = now
            r["missing"] = 0
            r["since"] = prev.get("since") if prev.get("in_stock") == r["in_stock"] and prev.get("ok") else now
        except Exception as ex:  # one bad product must not stop the rest
            gone = "不存在" in str(ex) or "下架" in str(ex)
            if gone:
                # removed on the shop: hidden right away; after two runs in a row it counts as confirmed (same idea as PriceAI)
                n = prev.get("missing", 0) + 1
                r = {"goods_no": g, "plan": it["plan"], "type": it["type"], "ok": False, "missing": n,
                     "why": "商品已下架" if n >= 2 else "商品暂时读不到，等下一轮确认",
                     "gone_since": prev.get("gone_since") or now, "shop": prev.get("shop", ""), "title": prev.get("title", "")}
            elif prev.get("ok") and prev.get("checked") and now_dt - dt.datetime.fromisoformat(prev["checked"]) < dt.timedelta(hours=GRACE_HOURS):
                # network / API hiccup: keep showing the last good reading, marked as such
                r = dict(prev, stale=True, why=f"本轮读取失败，显示 {prev['checked'][:16]} 的数据")
            else:
                r = {"goods_no": g, "plan": it["plan"], "type": it["type"], "ok": False, "why": f"连续读取失败：{ex}"[:80],
                     "shop": prev.get("shop", ""), "title": prev.get("title", "")}
        out.append(r)
        time.sleep(0.8)
    removed = [r for r in out if r.get("missing", 0) >= 2 and r.get("gone_since")
               and now_dt - dt.datetime.fromisoformat(r["gone_since"]) > dt.timedelta(days=7)]
    if removed:  # shown in the Actions log; delete these lines from watch.json
        print("下架超过 7 天，建议从 watch.json 删除：", ", ".join(r["goods_no"] for r in removed))
    json.dump({"time": now, "source": "16688 公开商品页接口", "items": out},
              open(os.path.join(DIR, "shops.json"), "w"), ensure_ascii=False, indent=1)
    hp = os.path.join(DIR, "shops_history.json")
    hist = json.load(open(hp)) if os.path.exists(hp) else {}
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for r in out:
        h = [x for x in hist.get(r["goods_no"], []) if x[0] >= cutoff]
        h.append([now, r.get("total") if r.get("ok") else None, 1 if r.get("ok") and r.get("in_stock") else 0])
        hist[r["goods_no"]] = h
    json.dump(hist, open(hp, "w"), ensure_ascii=False)
    print(f"checked {len(out)}: {sum(1 for r in out if r.get('ok'))} ok")


if __name__ == "__main__":
    main()

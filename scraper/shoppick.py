"""Keep data/merchants/watch.json filled with good public shop products, chosen by the site's own LLM.

The scaffold does the fetching and the hard rules; the model only chooses among checked candidates.
  1. candidates: data/channels/candidates.json (cheapest 代充 listings per plan from the 4-hourly 16688 crawl,
     titles that disclaim delivery or after-sales already removed)
  2. each candidate is read from 16688's public product page API (same calls as scraper/shopwatch.py):
     real price with fee, stock, shop age, deposit, buyers, and the fine print in the description
  3. the model picks up to MAX_PER_PLAN per plan and says why (prompt below)
  4. code checks the answer: only known candidates, in stock, no "可能不到账" style title, cap per plan
Runs after every shopwatch pass but only calls the model when a plan is short of live products,
or once a week (Monday) to refresh. Hand-added items (no "by": "ai") are never removed by the model,
only when the shop deletes them for two runs in a row.

python scraper/shoppick.py [--force]
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shopwatch  # noqa: E402

DIR = os.path.join(ROOT, "data", "merchants")
MIN_LIVE, MAX_PER_PLAN, PER_PLAN_CANDIDATES = 3, 5, 12
PLAN_NAMES = {"chatgpt/go": "ChatGPT Go", "chatgpt/plus": "ChatGPT Plus", "chatgpt/pro-100": "ChatGPT Pro 5x（$100）",
              "chatgpt/pro-200": "ChatGPT Pro 20x（$200）", "claude/pro": "Claude Pro", "claude/max-5x": "Claude Max 5x",
              "claude/max-20x": "Claude Max 20x", "google-ai/pro": "Google AI Pro（Gemini）", "grok/supergrok": "SuperGrok"}

PROMPT = """你在为比价网站「比比价」挑选要长期监控的卡网商品（代充：把会员充到买家自己的账号）。网站只展示、不推荐，所以要挑的是「价格有竞争力、条款说得清楚、出了问题有人管」的商品，让用户自己比较。

档位：{plan}
目前已在监控、仍有货的：{live}
候选（都已核实有货，total 是含手续费的实付人民币；risks 是从商品说明里找出的限制条款；desc 是说明原文节选）：
{cands}

挑选规则：
1. 必须是该档位的月付代充，标题和说明都指向同一个档位。档位对不上（例如候选是 ChatGPT Pro 5x，档位却是 Claude Max 5x）、年卡、周卡、成品号、资格号、教程，一律不选。
2. 说明里写明「不到账不负责/不退款」「封号不赔」「拍下不退」的，比同价位没写这些的要靠后；如果所有候选都有，就选写得最清楚、退款路径最明确的。
3. 价格越低越好，但比最低价贵 15% 以上的，除非条款明显更好，否则不选。
4. 店铺信号：有保证金、入驻时间长、付款人数多的优先。
5. 同一家店最多选 1 个商品。
6. 总数（已在监控的 + 新选的）不超过 {cap} 个；可以少选，宁缺毋滥。
7. 已在监控里的商品，如果你认为它不该再监控（档位不对、条款明显更差而且有更好的替代），放进 drop。

只输出 JSON：{{"picks":[{{"goods_no":"G...","reason":"一句话"}}],"drop":[{{"goods_no":"G...","reason":"一句话"}}]}}
"""


def chat(content):
    base, key, model = (os.environ.get(k, "") for k in ("SUPBI_AI_BASE_URL", "SUPBI_AI_API_KEY", "SUPBI_AI_MODEL"))
    if not (base and key and model):
        sys.exit("SUPBI_AI_* is not set; skipping")
    body = json.dumps({"model": model, "temperature": 0, "messages": [{"role": "user", "content": content}]}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                  "User-Agent": "Mozilla/5.0 (bbwith-shoppick/1.0)"})
            text = json.loads(urllib.request.urlopen(req, timeout=180).read())["choices"][0]["message"]["content"]
            text = re.sub(r"^.*?(\{)", r"\1", text.strip(), count=1, flags=re.S)
            return json.loads(text[:text.rfind("}") + 1])
        except Exception as ex:
            print("llm attempt failed:", repr(ex)[:200])
            time.sleep(8)
    return None


def goods_no_of(row):
    for k, v in row.items():
        if isinstance(v, str) and re.fullmatch(r"G\d{6,}", v):
            return v
    return None


def detail(goods_no, plan):
    """Public product page data plus a short, clean description for the model."""
    r = shopwatch.check({"goods_no": goods_no, "plan": plan, "type": "topup"})
    d = shopwatch.post("goods/detail", {"goods_no": goods_no}) or {}
    desc = re.sub(r"<[^>]+>", " ", d.get("description") or "")
    r["desc"] = re.sub(r"&nbsp;|\s+", " ", desc).strip()[:600]
    return r


def main():
    force = "--force" in sys.argv
    cand = json.load(open(os.path.join(ROOT, "data", "channels", "candidates.json"))).get("plans", {})
    wp = os.path.join(DIR, "watch.json")
    watch = json.load(open(wp))
    shops = {r["goods_no"]: r for r in json.load(open(os.path.join(DIR, "shops.json"))).get("items", [])} \
        if os.path.exists(os.path.join(DIR, "shops.json")) else {}
    today = dt.date.today()
    weekly = today.weekday() == 0
    lp = os.path.join(DIR, "pick_log.json")
    log = json.load(open(lp)) if os.path.exists(lp) else []
    ran_today = any(x.get("date") == today.isoformat() and x.get("full") for x in log)
    changed = False

    # shop deleted the product two runs in a row: remove it, whoever added it
    gone = {g for g, r in shops.items() if r.get("missing", 0) >= 2}
    if gone:
        watch["items"] = [it for it in watch["items"] if it["goods_no"] not in gone]
        log.append({"date": today.isoformat(), "removed_gone": sorted(gone)})
        changed = True

    for plan, rows in cand.items():
        if plan not in PLAN_NAMES:
            continue
        mine = [it for it in watch["items"] if it["plan"] == plan]
        live = [it for it in mine if shops.get(it["goods_no"], {}).get("ok") and shops.get(it["goods_no"], {}).get("in_stock")]
        if not force and len(live) >= MIN_LIVE and not (weekly and not ran_today):
            continue
        watched = {it["goods_no"] for it in mine}
        seen_shops = {shops.get(g, {}).get("shop_no") for g in watched}
        checked = []
        for row in rows:
            g = goods_no_of(row)
            if not g or g in watched:
                continue
            try:
                r = detail(g, plan)
            except Exception as ex:
                print("skip", g, repr(ex)[:80])
                continue
            if r.get("ok") and r.get("in_stock") and not shopwatch_title_risky(r["title"]):
                checked.append(r)
            if len(checked) >= PER_PLAN_CANDIDATES:
                break
            time.sleep(0.6)
        if not checked:
            print(plan, "no usable candidates")
            continue
        fields = ("goods_no", "shop", "title", "total", "warranty", "risks", "months", "deposit", "shop_sales", "sales", "desc")
        live_view = [{k: shops[it["goods_no"]].get(k) for k in ("goods_no", "shop", "title", "total", "risks")} for it in live]
        ans = chat(PROMPT.format(plan=PLAN_NAMES[plan], cap=MAX_PER_PLAN,
                                 live=json.dumps(live_view, ensure_ascii=False) if live_view else "（无）",
                                 cands=json.dumps([{k: c.get(k) for k in fields} for c in checked], ensure_ascii=False)))
        if not ans:
            continue
        ok_ids = {c["goods_no"]: c for c in checked}
        entry = {"date": today.isoformat(), "plan": plan, "full": True, "picked": [], "dropped": []}
        # drops: only items the model itself added, or anything the model calls the wrong plan
        for d in ans.get("drop", [])[:3]:
            g = d.get("goods_no")
            it = next((x for x in watch["items"] if x["goods_no"] == g and x["plan"] == plan), None)
            if it and (it.get("by") == "ai" or re.search(r"档位|不是|非", d.get("reason", ""))):
                watch["items"].remove(it)
                entry["dropped"].append({"goods_no": g, "reason": d.get("reason", "")[:80]})
        room = MAX_PER_PLAN - len([x for x in watch["items"] if x["plan"] == plan])
        for p in ans.get("picks", []):
            g = p.get("goods_no")
            c = ok_ids.get(g)
            if room <= 0 or not c or c.get("shop_no") in seen_shops:
                continue
            watch["items"].append({"goods_no": g, "plan": plan, "type": "topup", "added": today.isoformat(), "by": "ai",
                                   "reason": (p.get("reason") or "")[:80]})
            seen_shops.add(c.get("shop_no"))
            entry["picked"].append({"goods_no": g, "shop": c["shop"], "total": c["total"], "reason": (p.get("reason") or "")[:80]})
            room -= 1
        log.append(entry)
        changed = changed or entry["picked"] or entry["dropped"]
        print(plan, "picked", [x["goods_no"] for x in entry["picked"]], "dropped", [x["goods_no"] for x in entry["dropped"]])

    if changed:
        json.dump(watch, open(wp, "w"), ensure_ascii=False, indent=1)
    json.dump(log[-200:], open(lp, "w"), ensure_ascii=False, indent=1)


def shopwatch_title_risky(title):
    return bool(re.search(r"不包到账|不保到账|不保证到账|可能不到账|秒封不保|封号不保|无售后|不售后", title))


if __name__ == "__main__":
    main()

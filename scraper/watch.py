"""Daily watch of official AI pricing pages: plans, prices and limited-time promotions.

Each page is opened in headless Chromium (pricing pages are usually rendered by JavaScript), the visible text
is extracted, and an LLM turns it into structured plans and promotions. Only what the page says is kept.
Output: data/pricing/latest.json (current state) and data/pricing/changes.json (detected changes).

env: SUPBI_AI_BASE_URL, SUPBI_AI_API_KEY, SUPBI_AI_MODEL
python scraper/watch.py [--only id,id] [--no-llm]
"""
import datetime as dt, json, os, re, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = json.load(open(os.path.join(ROOT, "scraper", "watch_targets.json"), encoding="utf8"))
OUT = os.path.join(ROOT, "data", "pricing")
SHOTS = os.environ.get("SHOTS_DIR", "/tmp/shots")

PROMPT = """下面是「{name}」官网价格页（{url}）在 {date} 的可见文字。请只根据这段文字提取：
1. 付费方案：名称、价格（数字）、货币（ISO 代码，如 USD、CNY、EUR）、计费周期（month / year / once / credits），以及一句话说明（如额度、主要权益，20 字以内）。同一方案有月付和年付就分两条。年付页面上显示的「折合每月」价格请写成 year 周期的总价；如果只给了折合月价，period 写 year_monthly。
2. 限时优惠：只算页面上明确写出的折扣、限时价、首月特价、节日活动、优惠码、免费试用天数等；写清楚优惠内容、适用对象和截止日期（页面写了才填，格式 YYYY-MM-DD）。「年付省 X%」这种长期存在的年付折扣不算限时优惠，放进 annual_discount。
不要猜测，页面没写的不要填。如果这段文字不是价格页（例如登录页、验证页、错误页），ok 填 false。

只输出 JSON：
{{"ok": true, "currency": "USD",
  "plans": [{{"name": "Pro", "price": 20, "currency": "USD", "period": "month", "note": "..."}}],
  "annual_discount": "年付省 17%（如有）",
  "promos": [{{"title": "黑五 5 折", "detail": "...", "audience": "新用户 / 所有人 / 学生 ...", "ends": "2026-12-01"}}]}}

页面文字：
{text}"""


def llm(prompt):
    base, key, model = (os.environ.get(k, "") for k in ("SUPBI_AI_BASE_URL", "SUPBI_AI_API_KEY", "SUPBI_AI_MODEL"))
    body = json.dumps({"model": model, "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                  "User-Agent": "Mozilla/5.0 (bbwith-watch/1.0)", "Accept": "application/json"})
            text = json.loads(urllib.request.urlopen(req, timeout=180).read())["choices"][0]["message"]["content"]
            text = text[text.find("{"):text.rfind("}") + 1]
            return json.loads(text)
        except urllib.error.HTTPError as e:
            print("  llm", e.code, e.read()[:200])
        except Exception as e:
            print("  llm", repr(e)[:200])
        time.sleep(8)
    return None


def render_all(targets):
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, locale="en-US",
                            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        for t in targets:
            pg = ctx.new_page()
            try:
                pg.goto(t["url"], wait_until="domcontentloaded", timeout=45000)
                try:
                    pg.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                pg.wait_for_timeout(2500)
                text = pg.evaluate("document.body ? document.body.innerText : ''")
                pg.screenshot(path=os.path.join(SHOTS, f"{t['id']}.jpg"), full_page=True, type="jpeg", quality=45)
                out[t["id"]] = {"final_url": pg.url, "title": pg.title(), "text": re.sub(r"\n{3,}", "\n\n", text)[:14000]}
                print(f"{t['id']}: {len(text)} chars, {pg.url}")
            except Exception as e:
                out[t["id"]] = {"error": repr(e)[:200]}
                print(f"{t['id']}: failed {repr(e)[:120]}")
            finally:
                pg.close()
        b.close()
    return out


def key_of(plan):
    return f"{plan.get('name', '').strip().lower()}|{plan.get('period', '')}"


def main():
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)
    targets = [t for t in TARGETS if not only or t["id"] in only]
    os.makedirs(OUT, exist_ok=True)
    lpath, cpath = os.path.join(OUT, "latest.json"), os.path.join(OUT, "changes.json")
    prev = json.load(open(lpath)) if os.path.exists(lpath) else {"products": {}}
    changes = json.load(open(cpath)) if os.path.exists(cpath) else []
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    stamp = now.strftime("%Y-%m-%d %H:%M")
    pages = render_all(targets)
    products = dict(prev.get("products", {}))
    for t in targets:
        pg = pages.get(t["id"], {})
        old = products.get(t["id"], {})
        entry = {"id": t["id"], "name": t["name"], "url": t["url"], "region": t["region"], "checked": stamp}
        if "--no-llm" in sys.argv or "text" not in pg or len(pg["text"]) < 300:
            entry.update({k: old.get(k) for k in ("plans", "promos", "annual_discount", "updated") if k in old})
            entry["status"] = "页面打不开" if "error" in pg else "页面内容太少（可能需要登录或被拦截）"
            products[t["id"]] = entry
            continue
        r = llm(PROMPT.format(name=t["name"], url=t["url"], date=now.date().isoformat(), text=pg["text"]))
        if not r or not r.get("ok"):
            entry.update({k: old.get(k) for k in ("plans", "promos", "annual_discount", "updated") if k in old})
            entry["status"] = "没有识别到价格（可能是登录页或验证页）"
            products[t["id"]] = entry
            print(f"  {t['id']}: no pricing recognised")
            continue
        plans = [p for p in r.get("plans", []) if isinstance(p.get("price"), (int, float))]
        promos = [p for p in r.get("promos", []) if p.get("title")]
        entry.update({"status": "ok", "plans": plans, "promos": promos, "annual_discount": r.get("annual_discount") or "",
                      "updated": stamp})
        # changes vs the previous successful read
        if old.get("plans"):
            before = {key_of(p): p for p in old["plans"]}
            for p in plans:
                q = before.get(key_of(p))
                if q and (q.get("price") != p.get("price") or q.get("currency") != p.get("currency")):
                    changes.append({"t": stamp, "id": t["id"], "kind": "price", "plan": p["name"], "period": p.get("period"),
                                    "from": f"{q.get('price')} {q.get('currency')}", "to": f"{p.get('price')} {p.get('currency')}"})
            old_promos = {x.get("title") for x in old.get("promos") or []}
            for x in promos:
                if x["title"] not in old_promos:
                    changes.append({"t": stamp, "id": t["id"], "kind": "promo", "title": x["title"], "detail": x.get("detail", "")})
        promo_first = {x.get("title"): x.get("first_seen") for x in old.get("promos") or []}
        for x in promos:
            x["first_seen"] = promo_first.get(x["title"]) or stamp
        products[t["id"]] = entry
        print(f"  {t['id']}: {len(plans)} plans, {len(promos)} promos")
    json.dump({"time": stamp, "products": products}, open(lpath, "w"), ensure_ascii=False, indent=1)
    json.dump(changes[-300:], open(cpath, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

"""Generate the static site for bbwith.com from data/daily/*.json.

Pure standard library, so it runs in the Cloudflare Pages build image as is:
  python3 site_src/generate.py   ->  dist/
"""
import csv
import datetime as dt
import glob
import html
import io
import json
import os
import shutil
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scraper"))
from plans import PLANS, PRODUCTS  # noqa: E402

SITE = "https://bbwith.com"
SITE_NAME = "比比价 bbwith"
DIST = os.path.join(ROOT, "dist")
COUNTRIES = json.load(open(os.path.join(HERE, "countries.json"), encoding="utf8"))
APP_OF_PRODUCT = {"chatgpt": ["chatgpt"], "claude": ["claude"], "google-ai": ["gemini", "googleone"], "grok": ["grok"],
                  "x": ["x"], "perplexity": ["perplexity"], "cursor": ["cursor"]}

e = html.escape


# ---------- data ----------

def load_days():
    files = sorted(glob.glob(os.path.join(ROOT, "data", "daily", "20*.json")))
    if not files:
        sys.exit("no data in data/daily")
    return [json.load(open(f, encoding="utf8")) for f in files]


def rows_of(day):
    """Expand a compact daily file into rows."""
    out = {}
    for key, per_cc in day["p"].items():
        product, plan = key.split("/")
        us_local = per_cc.get("us")
        us_usd = us_local / day["fx"]["USD"] if us_local else None
        rows = []
        for cc, local in per_cc.items():
            cur = day["cur"][cc]
            usd = local / day["fx"][cur]
            rows.append({"cc": cc, "currency": cur, "local": local, "display": day["disp"][key][cc],
                         "usd": usd, "cny": usd * day["usd_cny"], "vs_us": (usd / us_usd - 1) if us_usd else None})
        rows.sort(key=lambda r: r["usd"])
        out[(product, plan)] = rows
    return out


# ---------- helpers ----------

def flag(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc.upper())


def cname(cc):
    return COUNTRIES.get(cc, {}).get("zh", cc.upper())


def usd(v):
    return f"${v:,.2f}" if v < 1000 else f"${v:,.0f}"


def money(v):
    """A USD amount the page can show in another currency (see assets/sort.js)."""
    return f'<span class="m" data-usd="{v:.4f}">{usd(v)}</span>'


FX = {}  # filled in main(): currency -> units per USD, for the selector
FX_CHOICES = [("USD", "美元 USD"), ("CNY", "人民币 CNY"), ("EUR", "欧元 EUR"), ("GBP", "英镑 GBP"),
              ("JPY", "日元 JPY"), ("HKD", "港币 HKD"), ("SGD", "新加坡元 SGD")]


def cur_select():
    opts = "".join(f'<option value="{c}">{e(n)}</option>' for c, n in FX_CHOICES if c in FX)
    return f'<label class="cursel">显示币种 <select id="cur">{opts}</select></label>'



def pct(v):
    if v is None:
        return "—"
    s = f"{v * 100:+.0f}%"
    return "持平" if s in ("+0%", "-0%") else s


def zh_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"


def plan_label(product, plan):
    for p, pl, label, _ in PLANS:
        if p == product and pl == plan:
            return label
    return plan


def full_name(product, plan):
    return f'{PRODUCTS[product]["name"].split("（")[0]} {plan_label(product, plan)}'


def url_plan(product, plan):
    return f"/{product}/{plan}/"


def write(path, content):
    full = os.path.join(DIST, path.lstrip("/"))
    if full.endswith("/"):
        full += "index.html"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf8") as f:
        f.write(content)


def jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c") + "</script>"


def page(title, description, path, body, ld=(), date=None):
    canonical = SITE + path
    lds = "\n".join(jsonld(x) for x in ld)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="zh_CN">
<meta name="twitter:card" content="summary">
{f'<meta property="article:modified_time" content="{date}">' if date else ''}
<meta name="msvalidate.01" content="939B2495BA3A4866A1D2B018A6455FBC">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/style.css">
<link rel="alternate" type="application/json" href="/data/latest.json" title="最新价格数据">
<script>window.FX={json.dumps(FX)}</script>
{lds}
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="/"><span class="logo">比</span>比比价 <small>bbwith.com</small></a>
<nav><a href="/daily/">日报</a><a href="/data/">数据下载</a><a href="/about/">方法说明</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="foot"><div class="wrap">
<p>比比价（bbwith.com）整理各地区 App Store 公开标价，仅供参考。本站与 OpenAI、Anthropic、Google、SpaceX/xAI、X、Perplexity、Cursor 均无关联。实际价格、可订阅档位和税费以结账页为准；跨地区订阅需遵守 Apple 和各服务商的条款。</p>
<p><a href="/about/">数据来源与方法</a> · <a href="/data/">数据下载</a> · <a href="/llms.txt">llms.txt</a></p>
</div></footer>
<script src="/assets/sort.js" defer></script>
</body>
</html>
"""


def rank_html(rows, n=3, sep="<br>"):
    """Top-n cheapest regions with % vs US, as HTML."""
    out = []
    for i, r in enumerate(rows[:n], 1):
        vs = f'（<span class="{"down" if (r["vs_us"] or 0) < -0.005 else ("up" if (r["vs_us"] or 0) > 0.005 else "")}">{pct(r["vs_us"])}</span>）' if r["vs_us"] is not None else ""
        out.append(f'<span class="rk"><i>{i}</i>{flag(r["cc"])}&nbsp;{e(cname(r["cc"]))}&nbsp;<b>{money(r["usd"])}</b>{vs}</span>')
    return sep.join(out)


def rank_text(rows, n=3):
    return "、".join(f"{i}. {cname(r['cc'])} {usd(r['usd'])}（{pct(r['vs_us'])}）" for i, r in enumerate(rows[:n], 1))


def crumbs(items):
    """items: [(name, path)]"""
    html_ = '<nav class="crumbs">' + " / ".join(
        f'<a href="{p}">{e(n)}</a>' if i < len(items) - 1 else f"<span>{e(n)}</span>" for i, (n, p) in enumerate(items)) + "</nav>"
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + p} for i, (n, p) in enumerate(items)]}
    return html_, ld


def price_table(rows, prev=None, limit=None, cls=""):
    head = "<tr><th>#</th><th>地区</th><th data-sort=num>价格（<span class=mh>USD</span>）</th><th>本地标价</th><th data-sort=num>比美区</th>" + \
           ("<th data-sort=num>较前一日</th>" if prev is not None else "") + "</tr>"
    body = []
    for i, r in enumerate(rows[:limit] if limit else rows, 1):
        chg = ""
        if prev is not None:
            p = prev.get(r["cc"])
            if p is None:
                chg = '<td data-v="0">新增</td>'
            elif p["currency"] != r["currency"] or abs(p["local"] - r["local"]) < 1e-9:
                chg = '<td data-v="0">—</td>'
            else:
                d = r["local"] / p["local"] - 1
                chg = f'<td data-v="{d:.4f}" class="{"down" if d < 0 else "up"}">{d * 100:+.1f}%</td>'
        us = ' class="us"' if r["cc"] == "us" else ""
        vs = r["vs_us"]
        body.append(f'<tr{us}><td>{i}</td><td>{flag(r["cc"])} {e(cname(r["cc"]))}</td><td data-v="{r["usd"]:.4f}"><b>{money(r["usd"])}</b></td>'
                    f'<td>{e(r["display"])} <small>{r["currency"]}</small></td>'
                    f'<td data-v="{vs if vs is not None else 0:.4f}" class="{"down" if (vs or 0) < -0.005 else ("up" if (vs or 0) > 0.005 else "")}">{pct(vs)}</td>{chg}</tr>')
    return f'<div class="tablewrap"><table class="prices sortable {cls}"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def summary_sentence(product, plan, rows, day):
    name = full_name(product, plan)
    us = next((r for r in rows if r["cc"] == "us"), None)
    lo, hi = rows[0], rows[-1]
    med = statistics.median(r["usd"] for r in rows)
    s = (f"截至{zh_date(day['date'])}，{name} 在 {len(rows)} 个 App Store 地区可以查到月付标价。"
         f"最便宜的是{cname(lo['cc'])}（{lo['display']}，约 {usd(lo['usd'])}"
         + (f"，比美区{'低' if lo['vs_us'] < 0 else '高'} {abs(lo['vs_us']) * 100:.0f}%" if lo["vs_us"] is not None and abs(lo["vs_us"]) >= 0.005 else "") + "），"
         f"最贵的是{cname(hi['cc'])}（{hi['display']}，约 {usd(hi['usd'])}）")
    if us:
        s += f"；美区标价 {us['display']}"
    s += f"；所有地区的中位数约 {usd(med)}。价格均为按当日汇率折算的美元。"
    return s


# ---------- pages ----------

CHANNELS = {}  # latest data/channels/*.json, loaded in main()
ROUTE_LABELS = {"ph": "菲区卡充", "us-ios": "美区 iOS", "eg": "埃及卡充", "cl": "智利卡充", "jp": "日区", "tr": "土区", "other": "未注明渠道"}


def load_channels():
    files = sorted(glob.glob(os.path.join(ROOT, "data", "channels", "20*.json")))
    return json.load(open(files[-1], encoding="utf8")) if files else {}


# channel plan key -> App Store plan it is the same subscription as
CHANNEL_TO_PLAN = {"chatgpt/go": ("chatgpt", "go"), "chatgpt/plus": ("chatgpt", "plus"), "chatgpt/pro-100": ("chatgpt", "pro-100"),
                   "chatgpt/pro-200": ("chatgpt", "pro-200"), "chatgpt/pro-500": ("chatgpt", "pro-500"),
                   "claude/pro": ("claude", "pro"), "claude/max-5x": ("claude", "max"), "claude/max-20x": ("claude", "ultra"),
                   "google-ai/pro": ("google-ai", "pro"), "grok/supergrok": ("grok", "supergrok"),
                   "grok/supergrok-heavy": ("grok", "supergrok-heavy"), "cursor/pro": ("cursor", "pro"),
                   "cursor/pro-plus": ("cursor", "pro-plus"), "cursor/ultra": ("cursor", "ultra")}
CHANNEL_LABELS = {"chatgpt/team": "Team / Business", "claude/max-5x": "Max 5x", "claude/max-20x": "Max 20x（App Store 称 Ultra）",
                  "claude/team": "Team", "google-ai/plus": "AI Plus", "google-ai/ultra": "Ultra（卖家档位不一）", "grok/plus": "Grok Plus（8 美元档）"}
TYPE_ORDER = [("topup", "代充（充到自己账号）"), ("account-long", "成品号（质保 ≥ 25 天）"), ("account-short", "成品号（短质保 / 首登）"),
              ("seat", "Team / 车位"), ("shared", "拼车 / 共享 / 镜像"), ("promo", "优惠渠道（半价、学生、活动链接）")]


def channel_key_for(product, plan):
    return next((k for k, v in CHANNEL_TO_PLAN.items() if v == (product, plan)), None)


def channel_label(key):
    product, plan = key.split("/", 1)
    if key in CHANNEL_LABELS:
        return f'{PRODUCTS[product]["name"].split("（")[0]} {CHANNEL_LABELS[key]}'
    mp = CHANNEL_TO_PLAN.get(key)
    return full_name(*mp) if mp else key


def types_table(types, rate):
    rows = ""
    for t, label in TYPE_ORDER:
        v = types.get(t)
        if not v:
            continue
        rows += (f'<tr><td>{e(label)}</td><td>{v["count"]}</td><td data-v="{v["min"] / rate:.2f}">{money(v["min"] / rate)}</td>'
                 f'<td data-v="{v["median"] / rate:.2f}"><b>{money(v["median"] / rate)}</b></td></tr>')
    return (f'<div class="tablewrap"><table class="prices sortable"><thead><tr><th>交付方式</th><th>报价数</th><th data-sort=num>最低</th>'
            f'<th data-sort=num>中位数</th></tr></thead><tbody>{rows}</tbody></table></div>')


def channel_note():
    t = CHANNELS.get("time", "")[:16].replace("T", " ")
    return (f'<p class="note">数据来自国内卡网货源平台，价格为货源标价，零售店铺通常会加价；只统计月付，年卡、周卡、资格号、教程等不计入，明显偏离的引流低价已剔除。'
            f'更新于 {e(t)}（北京时间）。代充、成品号都属于第三方服务，有掉订阅、封号等风险，本站不展示具体卖家，也不做担保。</p>')


def channel_block(product, plan, rows):
    """Domestic channel prices (代充 / 成品号 / ...) for an App Store plan, or ""."""
    key = channel_key_for(product, plan)
    types = CHANNELS.get("plans", {}).get(key) if key else None
    if not types or sum(v["count"] for v in types.values()) < 3:
        return ""
    rate = CHANNELS["usd_cny"]
    us = next((r for r in rows if r["cc"] == "us"), None)
    lead = ""
    top = types.get("topup")
    if top and top["count"] >= 3:
        med = top["median"] / rate
        lead = (f"「{full_name(product, plan)}」代充到自己账号共有 <b>{top['count']}</b> 条报价，最低 {money(top['min'] / rate)}，"
                f"中位数 <b>{money(med)}</b>")
        if us:
            d = med / us["usd"] - 1
            lead += f"，比美区 App Store 标价{'低' if d < 0 else '高'} {abs(d) * 100:.0f}%"
        lead += "。"
    route_html = ""
    if top and top.get("routes"):
        rr = sorted(top["routes"].items(), key=lambda kv: kv[1]["median"])
        rrows = "".join(f'<tr><td>{e(ROUTE_LABELS.get(k, k))}</td><td>{v["count"]}</td><td data-v="{v["min"] / rate:.2f}">{money(v["min"] / rate)}</td>'
                        f'<td data-v="{v["median"] / rate:.2f}"><b>{money(v["median"] / rate)}</b></td></tr>' for k, v in rr if v["count"] >= 2)
        if rrows:
            route_html = (f'<h3>代充按充值渠道</h3><div class="tablewrap"><table class="prices sortable"><thead><tr><th>卖家注明的渠道</th><th>报价数</th>'
                          f'<th data-sort=num>最低</th><th data-sort=num>中位数</th></tr></thead><tbody>{rrows}</tbody></table></div>')
    return f"""<div class="bar"><h2>国内渠道参考价</h2>{cur_select()}</div>
{f'<p class="lead">{lead}</p>' if lead else ''}
{types_table(types, rate)}
{route_html}
{channel_note()}
"""


def product_channels(product):
    plans = {k: v for k, v in CHANNELS.get("plans", {}).items() if k.startswith(product + "/") and sum(t["count"] for t in v.values()) >= 3}
    if not plans:
        return ""
    rate = CHANNELS["usd_cny"]
    order = list(CHANNEL_TO_PLAN) + list(CHANNEL_LABELS)
    rows = ""
    for k in sorted(plans, key=lambda k: order.index(k) if k in order else 99):
        v = plans[k]
        mp = CHANNEL_TO_PLAN.get(k)
        name = f'<a href="{url_plan(*mp)}">{e(channel_label(k))}</a>' if mp else e(channel_label(k))
        cell = lambda t: money(v[t]["median"] / rate) + f' <small>{v[t]["count"]} 条</small>' if t in v else "—"
        rows += f'<tr><td>{name}</td><td>{cell("topup")}</td><td>{cell("account-long")}</td><td>{cell("account-short")}</td><td>{cell("seat")}</td></tr>'
    return f"""<div class="bar"><h2>国内渠道参考价（中位数）</h2>{cur_select()}</div>
<div class="tablewrap"><table class="prices"><thead><tr><th>档位</th><th>代充</th><th>成品号（长质保）</th><th>成品号（短质保）</th><th>Team / 车位</th></tr></thead><tbody>{rows}</tbody></table></div>
{channel_note()}"""


def build_plan_page(product, plan, rows, prev_rows, day, all_plans):
    name = full_name(product, plan)
    path = url_plan(product, plan)
    date = day["date"]
    us = next((r for r in rows if r["cc"] == "us"), None)
    lo = rows[0]
    title = f"{name} 哪个地区最便宜？{len(rows)} 个 App Store 地区价格对比（{zh_date(date)}）"
    desc = (f"{name} 今日最低：{cname(lo['cc'])} {lo['display']}，约 {usd(lo['usd'])}。"
            f"统一折算成美元，对比 {len(rows)} 个 App Store 地区的月付标价，每日更新。")
    cr_html, cr_ld = crumbs([("首页", "/"), (PRODUCTS[product]["name"], f"/{product}/"), (plan_label(product, plan), path)])
    prev_map = {r["cc"]: r for r in prev_rows} if prev_rows is not None else None
    cheaper = [r for r in rows if r["vs_us"] is not None and r["vs_us"] < -0.005]
    apps = APP_OF_PRODUCT[product]
    unavailable = sorted({cc for a in apps for cc in day["unavailable"].get(a, [])
                          if all(cc in day["unavailable"].get(b, []) for b in apps)})
    missing = sorted(set(day["storefronts"]) - {r["cc"] for r in rows} - set(unavailable))
    siblings = " ".join(f'<a class="chip{" on" if pl == plan else ""}" href="{url_plan(p, pl)}">{e(label)}</a>'
                        for p, pl, label, _ in PLANS if p == product and (p, pl) in all_plans)
    faq = [
        (f"{name} 哪个地区最便宜？",
         f"按{zh_date(date)}的 App Store 标价和汇率，最便宜的 5 个地区是："
         + "、".join(f"{cname(r['cc'])}（约 {usd(r['usd'])}）" for r in rows[:5]) + "。"),
        (f"{name} 美区多少钱？",
         f"美区 App Store 标价 {us['display']} / 月。美区标价不含销售税，结账时会按所在州另加。" if us else "本次没有抓到美区标价。"),
        ("这些价格含税吗？",
         "大多数地区的 App Store 标价已经包含增值税或消费税；美国、加拿大等地区的标价不含税，结账时另加。"),
        (f"{name} 有多少个地区比美区便宜？",
         f"{len(rows)} 个地区里，有 {len(cheaper)} 个地区折合美元后比美区便宜 0.5% 以上。"),
    ]
    faq_html = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)
    body = f"""{cr_html}
<h1>{e(name)} 各地区 App Store 价格</h1>
<p class="meta">更新于 {zh_date(date)} · 月付标价 · 按当日汇率折算（{e(day['fx_source'])}）</p>
<p class="lead">{e(summary_sentence(product, plan, rows, day))}</p>
<div class="chips">{siblings}</div>
<div class="bar"><h2>最便宜的 10 个地区</h2>{cur_select()}</div>
{price_table(rows, limit=10)}
{channel_block(product, plan, rows)}
<h2>全部 {len(rows)} 个地区</h2>
<p class="hint">点击表头可以排序。美区一行已高亮。</p>
{price_table(rows, prev=prev_map)}
{f'<p class="note">在以下地区 App Store 无法下载这个 App：{"、".join(cname(c) for c in unavailable)}。</p>' if unavailable else ''}
{f'<p class="note">以下地区能下载 App，但本次没有抓到这一档的标价（App Store 每个 App 只展示约 10 个内购项目）：{"、".join(cname(c) for c in missing[:40])}{" 等" if len(missing) > 40 else ""}。</p>' if missing else ''}
{f'<p class="note">{e(PRODUCTS[product]["note"])}</p>' if PRODUCTS[product]["note"] else ''}
<h2>常见问题</h2>
<div class="faq">{faq_html}</div>
<p class="src">数据来源：各地区 App Store 公开页面的「App 内购买项目」。<a href="/about/">查看方法说明</a> · <a href="/data/">下载数据</a></p>
"""
    ld = [cr_ld,
          {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
          {"@context": "https://schema.org", "@type": "Dataset", "name": f"{name} App Store 各地区月付价格",
           "description": desc, "url": SITE + path, "dateModified": date, "temporalCoverage": date,
           "license": "https://creativecommons.org/licenses/by/4.0/",
           "creator": {"@type": "Organization", "name": SITE_NAME, "url": SITE},
           "variableMeasured": ["本地标价", "折算美元价格", "相对美区差价"],
           "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{SITE}/data/latest.csv"},
                            {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": f"{SITE}/data/latest.json"}]}]
    write(path, page(title, desc, path, body, ld, date))


def build_product_page(product, plans_rows, day):
    path = f"/{product}/"
    info = PRODUCTS[product]
    cr_html, cr_ld = crumbs([("首页", "/"), (info["name"], path)])
    rows_html = []
    for (p, pl), rows in plans_rows:
        us = next((r for r in rows if r["cc"] == "us"), None)
        lo = rows[0]
        rows_html.append(f'<tr><td><a href="{url_plan(p, pl)}">{e(plan_label(p, pl))}</a></td><td>{e(us["display"]) if us else "—"}</td>'
                         f'<td>{rank_html(rows, 3)}</td><td>{len(rows)}</td></tr>')
    name0 = info["name"].split("（")[0]
    title = f"{name0} 会员各地区 App Store 价格对比：哪个地区最便宜（{zh_date(day['date'])}）"
    desc = f"{name0} 各档会员在 {len(day['storefronts'])} 个 App Store 地区的月付标价，统一折算成美元，对比最便宜和最贵的地区，每日更新。"
    body = f"""{cr_html}
<h1>{e(info['name'])} 各档会员 App Store 价格</h1>
<p class="meta">更新于 {zh_date(day['date'])} · App：{e(info['app'])}（{e(info['vendor'])}）</p>
{f'<p class="note">{e(info["note"])}</p>' if info["note"] else ''}
<div class="bar"><h2>各档位最便宜地区</h2>{cur_select()}</div>
<div class="tablewrap"><table class="prices"><thead><tr><th>档位</th><th>美区标价</th><th>最便宜的 3 个地区（<span class=mh>USD</span>）</th><th>地区数</th></tr></thead>
<tbody>{''.join(rows_html)}</tbody></table></div>
{product_channels(product)}
<p class="src"><a href="/about/">方法说明</a> · <a href="/data/">数据下载</a></p>
"""
    write(path, page(title, desc, path, body, [cr_ld], day["date"]))


def headline_rows(cur):
    keys = [("chatgpt", "plus"), ("chatgpt", "go"), ("claude", "pro"), ("google-ai", "pro"), ("grok", "supergrok"),
            ("x", "premium"), ("perplexity", "pro"), ("cursor", "pro")]
    return [(k, cur[k]) for k in keys if k in cur]


def changes(cur, prev):
    out = []
    if prev is None:
        return out
    for key, rows in cur.items():
        pm = {r["cc"]: r for r in prev.get(key, [])}
        for r in rows:
            p = pm.get(r["cc"])
            if p and p["currency"] == r["currency"] and abs(p["local"] - r["local"]) > 1e-9:
                out.append((key, r, p, r["local"] / p["local"] - 1))
    out.sort(key=lambda x: x[3])
    return out


def daily_channels(cur):
    plans = CHANNELS.get("plans", {})
    rate = CHANNELS.get("usd_cny")
    rows = []
    for key, mp in CHANNEL_TO_PLAN.items():
        top = plans.get(key, {}).get("topup")
        if not top or top["count"] < 3 or mp not in cur:
            continue
        us = next((r for r in cur[mp] if r["cc"] == "us"), None)
        med = top["median"] / rate
        d = (med / us["usd"] - 1) if us else None
        rows.append(f'<tr><td><a href="{url_plan(*mp)}">{e(full_name(*mp))}</a></td><td><b>{money(med)}</b> <small>{top["count"]} 条</small></td>'
                    f'<td>{money(us["usd"]) if us else "—"}</td><td class="{"down" if (d or 0) < 0 else "up"}">{pct(d)}</td>'
                    f'<td>{rank_html(cur[mp], 1)}</td></tr>')
    if not rows:
        return ""
    return f"""<div class="bar"><h2>国内代充 vs App Store</h2>{cur_select()}</div>
<div class="tablewrap"><table class="prices"><thead><tr><th>档位</th><th>代充中位数</th><th>美区 App Store</th><th>代充比美区</th><th>App Store 最便宜地区</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="note">代充价来自国内卡网货源平台，只统计充值到自己账号的月付代充。</p>"""


def build_daily(day, cur, prev_day, prev):
    date = day["date"]
    path = f"/daily/{date}/"
    title = f"AI 会员 App Store 价格日报（{zh_date(date)}）"
    chg = changes(cur, prev)
    facts = []
    for (p, pl), rows in headline_rows(cur):
        lo = rows[0]
        us = next((r for r in rows if r["cc"] == "us"), None)
        facts.append(f"<li><a href=\"{url_plan(p, pl)}\">{e(full_name(p, pl))}</a>"
                     + (f"（美区 {e(us['display'])}）" if us else "") + f"：{e(rank_text(rows))}</li>")
    if prev is None:
        chg_html = "<p>这是第一期日报，从明天开始会列出相对前一天的价格变动。</p>"
    elif not chg:
        chg_html = f"<p>与{zh_date(prev_day['date'])}相比，所有地区、所有档位的本地标价都没有变化（折算价会随汇率小幅波动）。</p>"
    else:
        items = "".join(f"<li>{e(full_name(*k))} · {flag(r['cc'])} {e(cname(r['cc']))}：{e(p['display'])} → {e(r['display'])}"
                        f"（<span class=\"{'down' if d < 0 else 'up'}\">{d * 100:+.1f}%</span>，现约 {usd(r['usd'])}）</li>"
                        for k, r, p, d in chg[:50])
        chg_html = f"<p>与{zh_date(prev_day['date'])}相比，共有 {len(chg)} 处本地标价变动：</p><ul>{items}</ul>"
    summary_rows = "".join(
        f'<tr><td><a href="{url_plan(p, pl)}">{e(full_name(p, pl))}</a><br><small>美区 {money(next((r["usd"] for r in rows if r["cc"] == "us"), 0))}</small></td>'
        + "".join(f"<td>{rank_html(rows[i:i + 1], 1)}</td>" if len(rows) > i else "<td>—</td>" for i in range(3)).replace("<i>1</i>", "")
        + '</tr>'
        for (p, pl), rows in sorted(cur.items(), key=lambda kv: [x[:2] for x in PLANS].index(kv[0])))
    desc = (f"{zh_date(date)} AI 会员 App Store 各地区价格日报：ChatGPT、Claude、Gemini、Grok、X、Perplexity、Cursor 共 "
            f"{len(cur)} 个档位的最便宜地区与价格变动。")
    cr_html, cr_ld = crumbs([("首页", "/"), ("日报", "/daily/"), (date, path)])
    body = f"""{cr_html}
<h1>{e(title)}</h1>
<p class="meta">覆盖 {len(day['storefronts'])} 个 App Store 地区 · 价格按当日汇率折算成美元</p>
<h2>今日要点</h2>
<ul class="facts">{''.join(facts)}</ul>
<h2>价格变动</h2>
{chg_html}
{daily_channels(cur)}
<div class="bar"><h2>各档位最便宜的 3 个地区</h2>{cur_select()}</div>
<div class="tablewrap"><table class="prices rank3"><thead><tr><th>档位</th><th>第 1 便宜</th><th>第 2 便宜</th><th>第 3 便宜</th></tr></thead><tbody>{summary_rows}</tbody></table></div>
"""
    ld = [cr_ld, {"@context": "https://schema.org", "@type": "Article", "headline": title, "datePublished": date,
                  "dateModified": date, "inLanguage": "zh-CN", "mainEntityOfPage": SITE + path,
                  "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE},
                  "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE}}]
    write(path, page(title, desc, path, body, ld, date))
    return chg


def build_daily_index(days):
    items = "".join(f'<li><a href="/daily/{d["date"]}/">{zh_date(d["date"])} 价格日报</a></li>' for d in reversed(days))
    cr_html, cr_ld = crumbs([("首页", "/"), ("日报", "/daily/")])
    body = f"""{cr_html}<h1>AI 会员 App Store 价格日报</h1>
<p class="lead">每天北京时间早上更新一次，记录各档会员在各地区 App Store 的最低价和标价变动。</p><ul class="list">{items}</ul>"""
    write("/daily/", page("AI 会员价格日报 · 比比价", "AI 会员 App Store 各地区价格日报归档，每天更新。", "/daily/", body, [cr_ld]))


def build_home(day, cur, chg, prev):
    date = day["date"]
    cards = []
    for product, info in PRODUCTS.items():
        plans = [(k, v) for k, v in cur.items() if k[0] == product]
        if not plans:
            continue
        plans.sort(key=lambda kv: [x[:2] for x in PLANS].index(kv[0]))
        lis = "".join(f'<li><a href="{url_plan(*k)}"><span>{e(plan_label(*k))}</span>'
                      f'<em>{rank_html(v, 3, "")}</em></a></li>' for k, v in plans)
        cards.append(f'<section class="card"><h3><a href="/{product}/">{e(info["name"])}</a></h3><ul>{lis}</ul></section>')
    facts = []
    for (p, pl), rows in headline_rows(cur)[:5]:
        lo = rows[0]
        facts.append(f"<li>{e(full_name(p, pl))} 最便宜的 3 个地区：{e(rank_text(rows))}。</li>")
    chg_line = (f"今天共有 {len(chg)} 处标价变动。" if chg else ("今天各地区标价没有变化。" if prev is not None else ""))
    title = f"AI 会员哪个地区最便宜？ChatGPT、Claude、Gemini、Grok 各地区 App Store 价格对比 | 比比价"
    desc = (f"每天对比 ChatGPT、Claude、Google AI（Gemini）、Grok、X Premium、Perplexity、Cursor 在 {len(day['storefronts'])} 个"
            f" App Store 地区的会员标价，统一折算成美元，找出最便宜的地区。")
    body = f"""<section class="hero">
<h1>AI 会员各地区价格，比比再买</h1>
<p class="lead">每天抓取 {len(day['storefronts'])} 个 App Store 地区的公开标价，按当日汇率统一折算成美元（也可以切换成其他币种）。最新数据：{zh_date(date)}。{chg_line}</p>
<ul class="facts">{''.join(facts)}</ul>
<p><a class="btn" href="/daily/{date}/">看今日日报</a></p>
</section>
<div class="bar"><h2>各档位最便宜的 3 个地区（月付）</h2>{cur_select()}</div>
<div class="cards">{''.join(cards)}</div>
<p class="src">价格为各地区 App Store 标价，大多数地区含税，美国、加拿大等地区不含税。<a href="/about/">方法说明</a></p>
"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE + "/", "inLanguage": "zh-CN"},
          {"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME, "url": SITE + "/"}]
    write("/", page(title, desc, "/", body, ld, date))


def build_about(day):
    cr_html, cr_ld = crumbs([("首页", "/"), ("方法说明", "/about/")])
    body = f"""{cr_html}<h1>数据来源与方法</h1>
<div class="prose">
<h2>数据来源</h2><p>价格来自各地区 App Store 公开页面上的「App 内购买项目」列表（apps.apple.com，英文界面），每天北京时间早上抓取一次，覆盖 {len(day['storefronts'])} 个 App Store 地区。</p>
<h2>汇率</h2><p>各地区本地标价按 open.er-api.com 当日汇率统一折算成美元；页面上可以切换成人民币、欧元等其他币种显示。本期汇率更新于 {e(day['fx_updated'])}。汇率每天都会波动，所以即使本地标价不变，折算价也会有小幅变化。</p>
<h2>只统计月付</h2><p>同一个内购名称在页面上可能同时对应月付和年付。高于美区月价 5 倍的价格视为年付，不计入；剩下的价格中取最高值作为常规月价，以排除首月优惠价。</p>
<h2>含税口径</h2><p>大多数地区的 App Store 标价已经包含增值税或消费税；美国、加拿大等地区的标价不含税，结账时按所在地另加。</p>
<h2>已知限制</h2><ul>
<li>App Store 每个 App 只展示约 10 个热门内购项目，所以部分档位在部分地区抓不到。</li>
<li>只统计 App Store，暂不包括 Google Play 和官网订阅价。官网价格请以结账页为准。</li>
<li>Google AI 只统计 Pro（5 TB）和 Ultra（30 TB）标准档；Google AI Plus 在不同地区附带的存储容量不同，暂未纳入。</li>
<li>Codex 没有单独的 iOS App，包含在 ChatGPT 套餐内。</li>
</ul>
<h2>国内渠道参考价</h2><p>各档位页和产品页另列了国内卡网货源平台的报价，每 4 小时更新一次。先把商品归到「产品 × 档位」，再按交付方式分开统计：代充（充到自己账号）、成品号（按质保是否满 25 天分两档）、Team / 车位、拼车 / 共享 / 镜像、优惠渠道（半价、学生、活动链接）。只统计月付，年卡、周卡、半价资格号、教程等不计入；低于中位数 30% 的引流价会被剔除。代充还按卖家注明的充值渠道（菲区卡充、美区 iOS 等）分组。本站不展示具体卖家，也不对任何卖家做担保。</p>
<h2>使用须知</h2><p>本站只做价格参考，不出售任何订阅，也不提供绕过地区限制的方法。跨地区订阅可能违反 Apple 或服务商的条款，请自行判断。</p>
<h2>引用与数据</h2><p>欢迎引用，请注明来源「比比价 bbwith.com」并附上链接。完整数据见 <a href="/data/">数据下载</a>，采用 CC BY 4.0 许可。</p>
</div>"""
    write("/about/", page("数据来源与方法 · 比比价", "比比价如何抓取和换算 App Store 各地区 AI 会员价格。", "/about/", body, [cr_ld]))


def build_data(days, cur):
    day = days[-1]
    os.makedirs(os.path.join(DIST, "data", "daily"), exist_ok=True)
    flat = []
    for (p, pl), rows in cur.items():
        for r in rows:
            flat.append({"date": day["date"], "product": p, "plan": pl, "plan_name": full_name(p, pl), "cc": r["cc"],
                         "country_zh": cname(r["cc"]), "country_en": COUNTRIES.get(r["cc"], {}).get("en", r["cc"].upper()),
                         "currency": r["currency"], "local_price": r["local"], "display": r["display"],
                         "usd": round(r["usd"], 2), "cny": round(r["cny"], 2),
                         "vs_us": round(r["vs_us"], 4) if r["vs_us"] is not None else None})
    meta = {"source": "App Store storefront pages (In-App Purchases)", "site": SITE, "license": "CC BY 4.0",
            "date": day["date"], "fx_source": day["fx_source"], "fx_updated": day["fx_updated"], "usd_cny": day["usd_cny"]}
    json.dump({"meta": meta, "rows": flat}, open(os.path.join(DIST, "data", "latest.json"), "w", encoding="utf8"),
              ensure_ascii=False, separators=(",", ":"))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(flat[0].keys()))
    w.writeheader()
    w.writerows(flat)
    with open(os.path.join(DIST, "data", "latest.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    for d in days:
        shutil.copy(os.path.join(ROOT, "data", "daily", f"{d['date']}.json"), os.path.join(DIST, "data", "daily", f"{d['date']}.json"))
    hist = "".join(f'<li><a href="/data/daily/{d["date"]}.json">{d["date"]}.json</a></li>' for d in reversed(days))
    cr_html, cr_ld = crumbs([("首页", "/"), ("数据下载", "/data/")])
    body = f"""{cr_html}<h1>数据下载</h1>
<p class="lead">最新一期（{zh_date(day['date'])}）共 {len(flat)} 条价格，采用 CC BY 4.0 许可，引用请注明「比比价 bbwith.com」。</p>
<ul class="list"><li><a href="/data/latest.csv">latest.csv</a>（Excel 可直接打开）</li><li><a href="/data/latest.json">latest.json</a></li></ul>
<h2>每日历史（紧凑格式）</h2><ul class="list">{hist}</ul>"""
    write("/data/", page("数据下载 · 比比价", "AI 会员 App Store 各地区价格数据下载，CSV 和 JSON。", "/data/", body, [cr_ld]))


def build_meta(days, cur):
    day = days[-1]
    urls = ["/", "/daily/", "/about/", "/data/"] + [f"/{p}/" for p in PRODUCTS if any(k[0] == p for k in cur)] + \
           [url_plan(*k) for k in cur] + [f"/daily/{d['date']}/" for d in days]
    sm = "".join(f"<url><loc>{SITE}{u}</loc><lastmod>{day['date'] if not u.startswith('/daily/20') else u.split('/')[2]}</lastmod></url>" for u in urls)
    write("/sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n')
    write("/robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    lines = [f"# 比比价 bbwith.com", "",
             f"> 每天对比 AI 会员在 {len(day['storefronts'])} 个 App Store 地区的标价，按当日汇率统一折算成美元。最新数据：{day['date']}。", "",
             "## 今日最便宜的 3 个地区（月付，App Store，比美区）", ""]
    for (p, pl), rows in sorted(cur.items(), key=lambda kv: [x[:2] for x in PLANS].index(kv[0])):
        lo = rows[0]
        us = next((r for r in rows if r["cc"] == "us"), None)
        lines.append(f"- [{full_name(p, pl)}]({SITE}{url_plan(p, pl)})" + (f"（美区 {us['display']}）" if us else "")
                     + "：" + "；".join(f"{i}. {COUNTRIES.get(r['cc'], {}).get('zh')}（{r['cc'].upper()}）{r['display']} ≈ ${r['usd']:.2f}，{pct(r['vs_us'])}" for i, r in enumerate(rows[:3], 1)))
    lines += ["", "## 页面", "", f"- [今日日报]({SITE}/daily/{day['date']}/)", f"- [方法说明]({SITE}/about/)",
              f"- [数据下载 CSV]({SITE}/data/latest.csv)", f"- [数据下载 JSON]({SITE}/data/latest.json)", "",
              "## 口径", "", "- 价格为各地区 App Store 公开标价，大多数地区含税，美国、加拿大等不含税。",
              "- 只统计月付；跨地区订阅需遵守 Apple 和服务商条款。", "- 引用请注明来源：比比价 bbwith.com。", ""]
    write("/llms.txt", "\n".join(lines))


def build_static():
    os.makedirs(os.path.join(DIST, "assets"), exist_ok=True)
    for f in ("style.css", "sort.js"):
        shutil.copy(os.path.join(HERE, "static", f), os.path.join(DIST, "assets", f))
    for f in os.listdir(os.path.join(HERE, "static")):
        if f in ("favicon.svg", "_headers", "_redirects", "404.html") or (f.endswith(".txt") and len(f) == 36):
            shutil.copy(os.path.join(HERE, "static", f), os.path.join(DIST, f))


def main():
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    days = load_days()
    day = days[-1]
    FX.update({"USD": 1.0, "CNY": day["usd_cny"]})
    FX.update({c: day["fx"][c] for c, _ in FX_CHOICES if c in day["fx"]})
    cur = rows_of(day)
    prev_day = days[-2] if len(days) > 1 else None
    prev = rows_of(prev_day) if prev_day else None
    CHANNELS.update(load_channels())
    for p, pl, _, _ in PLANS:
        if (p, pl) in cur:
            build_plan_page(p, pl, cur[(p, pl)], prev.get((p, pl)) if prev else None, day, cur)
    for product in PRODUCTS:
        pr = [(k, cur[k]) for k in [x[:2] for x in PLANS] if k[0] == product and k in cur]
        if pr:
            build_product_page(product, pr, day)
    chg = []
    for i, d in enumerate(days):
        c = rows_of(d)
        pv = rows_of(days[i - 1]) if i > 0 else None
        res = build_daily(d, c, days[i - 1] if i > 0 else None, pv)
        if i == len(days) - 1:
            chg = res
    build_daily_index(days)
    build_home(day, cur, chg, prev)
    build_about(day)
    build_data(days, cur)
    build_meta(days, cur)
    build_static()
    n = sum(len(fs) for _, _, fs in os.walk(DIST))
    print(f"built {n} files for {day['date']} into dist/")


if __name__ == "__main__":
    main()

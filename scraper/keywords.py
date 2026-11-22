"""Long-tail keyword discovery from search suggestions (Google and Baidu autocomplete).

Seeds x modifiers are sent to the public suggestion endpoints; every suggestion is kept with the seed that
produced it, how many seeds produced it, and whether one of our pages already targets it.
Output: data/keywords/latest.json and data/keywords/report.md (sorted, newest first)
"""
import datetime as dt, json, os, re, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "keywords")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

PRODUCTS = ["chatgpt plus", "chatgpt pro", "chatgpt go", "claude pro", "claude max", "gemini pro", "google ai pro",
            "supergrok", "grok", "cursor pro", "perplexity pro", "midjourney", "可灵", "lovart", "liblib"]
MODIFIERS = ["", " 多少钱", " 价格", " 哪个区最便宜", " 便宜", " 土耳其", " 土区", " 菲律宾", " 巴西", " 印度", " 订阅",
             " 怎么订阅", " 礼品卡", " 代充", " 国内", " 优惠", " 会员", " 苹果"]
GENERIC = ["土区apple id", "土耳其 apple id", "外区apple id", "苹果礼品卡 土耳其", "app store 礼品卡", "低价区订阅",
           "ai会员 便宜", "chatgpt 哪个区便宜", "苹果 换区", "美区礼品卡", "由我付"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    return urllib.request.urlopen(req, timeout=20).read()


def google(q):
    u = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode({"client": "firefox", "hl": "zh-CN", "q": q})
    return json.loads(get(u).decode("utf8", "replace"))[1]


def baidu(q):
    u = "https://suggestion.baidu.com/su?" + urllib.parse.urlencode({"wd": q, "action": "opensearch", "ie": "utf-8"})
    return json.loads(get(u).decode("utf8", "replace"))[1]


# rough map from a suggestion to the page that should rank for it
PAGE_RULES = [
    (r"apple ?id|苹果.*(账号|id)|换区|外区|土区.*(注册|账号)", "/guides/apple-id-low-price-region/"),
    (r"礼品卡|gift ?card|由我付", "/gift-cards/"),
    (r"chatgpt.*go", "/chatgpt/go/"), (r"chatgpt.*pro", "/chatgpt/"), (r"chatgpt|gpt plus", "/chatgpt/plus/"),
    (r"claude.*max", "/claude/max/"), (r"claude", "/claude/pro/"),
    (r"gemini|google ai|google one", "/google-ai/pro/"), (r"grok", "/grok/"), (r"cursor", "/cursor/pro/"),
    (r"perplexity", "/perplexity/pro/"), (r"midjourney|可灵|kling|lovart|liblib", "/ai-pricing/"),
]


def main():
    seeds = [p + m for p in PRODUCTS for m in MODIFIERS] + GENERIC
    found = {}
    for i, q in enumerate(seeds):
        for engine, fn in (("google", google), ("baidu", baidu)):
            try:
                for s in fn(q):
                    s = s.strip().lower()
                    if len(s) < 4 or s == q.strip().lower():
                        continue
                    k = found.setdefault(s, {"kw": s, "engines": set(), "seeds": set()})
                    k["engines"].add(engine)
                    k["seeds"].add(q.strip())
            except Exception as e:
                print(engine, q, repr(e)[:80])
            time.sleep(0.4)
        if i % 50 == 0:
            print(f"{i}/{len(seeds)} seeds, {len(found)} keywords")
    prev_path = os.path.join(OUT, "latest.json")
    prev = {x["kw"] for x in json.load(open(prev_path))["keywords"]} if os.path.exists(prev_path) else set()
    rows = []
    for k in found.values():
        page = next((p for rx, p in PAGE_RULES if re.search(rx, k["kw"], re.I)), "")
        rows.append({"kw": k["kw"], "engines": sorted(k["engines"]), "hits": len(k["seeds"]), "page": page,
                     "new": k["kw"] not in prev, "seed": sorted(k["seeds"])[0]})
    rows.sort(key=lambda r: (-len(r["engines"]), -r["hits"], r["kw"]))
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today().isoformat()
    json.dump({"date": today, "keywords": rows}, open(prev_path, "w"), ensure_ascii=False, indent=0)
    lines = [f"# 长尾关键词（{today}）", "", f"共 {len(rows)} 个；「两家都有」表示 Google 和百度都会联想出来，通常搜的人更多。", "",
             "| 关键词 | 来源 | 新出现 | 对应页面 |", "|---|---|---|---|"]
    for r in rows[:400]:
        lines.append(f"| {r['kw']} | {'两家都有' if len(r['engines']) == 2 else r['engines'][0]} | {'🆕' if r['new'] and prev else ''} | {r['page'] or '**缺页面**'} |")
    open(os.path.join(OUT, "report.md"), "w").write("\n".join(lines) + "\n")
    print(f"{len(rows)} keywords, {sum(1 for r in rows if not r['page'])} without a page")


if __name__ == "__main__":
    main()

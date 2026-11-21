"""Daily AI brief: collect yesterday's AI news from aggregators, let an LLM write an original Chinese brief.

Sources (all public, no login): Hacker News (stories + top comments), Google News RSS, OpenRouter new models,
official blogs / tech media RSS (same list as news.py) and Chinese AI media RSS.
The LLM only picks and rewrites; every item must cite source ids from the input, links come from our data.

env: SUPBI_AI_BASE_URL, SUPBI_AI_API_KEY, SUPBI_AI_MODEL (any OpenAI-compatible chat API)
python scraper/brief.py           # collect + write data/news/brief/<date>.json
python scraper/brief.py --dry     # collect only, print what would be sent
"""
import datetime as dt, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from news import FEEDS, parse  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "news", "brief")
UA = "bbwith-brief/1.0 (+https://bbwith.com/about/)"
HOURS = 30
EXTRA_FEEDS = ["https://www.jiqizhixin.com/rss", "https://www.qbitai.com/feed", "https://36kr.com/feed",
               "https://simonwillison.net/atom/everything/", "https://news.smol.ai/rss.xml"]
AI = re.compile(r"\bai\b|a\.i\.|llm|gpt|chatgpt|openai|claude|anthropic|gemini|deepmind|grok|xai|deepseek|qwen|kimi|moonshot|"
                r"mistral|llama|perplexity|cursor|copilot|codex|\bagents?\b|模型|智能体|人工智能|(?<![a-z])AI(?![a-z])", re.I)
PRODUCTS = ["chatgpt", "claude", "google-ai", "grok", "x", "perplexity", "cursor"]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def strip(s, n):
    s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
    return s[:n]


def hacker_news(since):
    q = urllib.parse.urlencode({"tags": "story", "hitsPerPage": 100,
                                "numericFilters": f"created_at_i>{int(since.timestamp())},points>60"})
    hits = get_json(f"https://hn.algolia.com/api/v1/search_by_date?{q}")["hits"]
    hits = [h for h in hits if AI.search(h.get("title") or "")]
    hits.sort(key=lambda h: -h["points"])
    out = []
    for i, h in enumerate(hits[:15]):
        item = {"source": "Hacker News", "title": h["title"], "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                "discuss": f"https://news.ycombinator.com/item?id={h['objectID']}", "points": h["points"],
                "comments_count": h.get("num_comments", 0)}
        if i < 6 and h.get("num_comments", 0) >= 20:
            try:
                kids = get_json(f"https://hn.algolia.com/api/v1/items/{h['objectID']}")["children"]
                item["comments"] = [strip(k.get("text"), 280) for k in kids if k.get("text")][:8]
            except Exception as e:
                print("hn comments failed", repr(e)[:80])
            time.sleep(0.5)
        out.append(item)
    return out


def google_news():
    q = "OpenAI OR ChatGPT OR Anthropic OR Claude OR Gemini OR Grok OR DeepSeek OR Qwen OR Perplexity OR Cursor when:1d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    return [{"source": "Google News", "title": it["title"], "url": it["link"]} for it in parse(url)[:35]]


def openrouter(since):
    models = get_json("https://openrouter.ai/api/v1/models")["data"]
    out = []
    for m in models:
        if m.get("created", 0) < since.timestamp() or ":free" in m["id"]:
            continue
        p = m.get("pricing", {})
        price = ""
        try:
            price = f"输入 ${float(p['prompt']) * 1e6:.2f} / 输出 ${float(p['completion']) * 1e6:.2f} 每百万 token"
        except Exception:
            pass
        out.append({"source": "OpenRouter 新上架模型", "title": m.get("name", m["id"]), "url": f"https://openrouter.ai/{m['id']}",
                    "desc": strip(m.get("description"), 300), "price": price, "context": m.get("context_length")})
    return out[:15]


def feeds(since):
    out = []
    for url in FEEDS + EXTRA_FEEDS:
        try:
            items = parse(url)
        except Exception as e:
            print("feed failed:", url, repr(e)[:100])
            continue
        for it in items:
            if it["when"] and it["when"].astimezone(dt.timezone.utc) < since:
                continue
            if not it["when"] or not AI.search(it["title"] + " " + it["desc"]):
                continue
            out.append({"source": urllib.parse.urlparse(url).netloc.replace("www.", ""), "title": it["title"], "url": it["link"],
                        "desc": strip(it["desc"], 240)})
    return out


def collect():
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=HOURS)
    items = []
    for name, fn in (("hn", lambda: hacker_news(since)), ("gnews", google_news), ("openrouter", lambda: openrouter(since)),
                     ("feeds", lambda: feeds(since))):
        try:
            got = fn()
        except Exception as e:
            print(name, "failed:", repr(e)[:120])
            got = []
        print(f"{name}: {len(got)}")
        items += got
    seen, uniq = set(), []
    for it in items:
        k = re.sub(r"\W+", "", it["title"].lower())[:60]
        if k and k not in seen and it.get("url"):
            seen.add(k)
            uniq.append(it)
    for i, it in enumerate(uniq[:110], 1):
        it["id"] = i
    return uniq[:110]


PROMPT = """你是中文网站「比比价 bbwith.com」的 AI 早报编辑。网站的读者是关心 ChatGPT、Claude、Gemini、Grok、Cursor 等 AI 会员和新模型的中文用户。

下面是过去一天从 Hacker News（含部分热门评论）、Google 新闻、OpenRouter 新上架模型、官方博客和科技媒体收集到的条目（JSON，每条有 id）。
请挑出最值得读者知道的 5～8 件事，写一期早报。优先级：新模型发布和评测口碑 > 会员/价格/限额变化 > 重要产品功能 > 行业大事。忽略融资八卦、和 AI 关系不大的内容。同一件事的多个条目合并成一条。

写作要求：
- items 按对读者的重要性从高到低排列。
- 小标题要带上产品或模型名（如「Gemini 4 Neon …」），让人一眼知道说的是谁。
- summary 讲清三件事：发生了什么、关键数字（只用输入里出现的）、对普通用户或会员用户意味着什么（例如哪档会员能用、是否免费、价格怎么变；输入没说就不写）。不要堆砌架构参数之类的技术细节。
- 语气客观克制，不夸张，不用「重磅」「炸裂」之类的词，不做推销。
- 全部用你自己的话写简体中文，不要翻译或照抄原文句子，不要引用超过 10 个字的原话。
- 只写输入里有的事实，不要补充输入以外的数字、日期或传闻；不确定的写「据报道」。
- 有 Hacker News 评论的条目，用一两句话概括社区的主要看法（好评和质疑都写），不要点名评论者。
- 每条必须在 sources 里列出支撑它的条目 id（1～4 个）。

只输出一个 JSON 对象，不要任何其他文字：
{"headline": "今日看点，一句话，30 字以内",
 "items": [{"title": "小标题，25 字以内",
            "summary": "2～3 句话讲清楚发生了什么、为什么重要",
            "take": "社区怎么看，1～2 句；没有评论素材就留空字符串",
            "kind": "model | pricing | product | industry 之一",
            "products": ["从 chatgpt, claude, google-ai, grok, x, perplexity, cursor 里选相关的，可以为空"],
            "sources": [1, 2]}]}

条目：
"""


def ask_llm(items):
    base, key, model = (os.environ.get(k, "") for k in ("SUPBI_AI_BASE_URL", "SUPBI_AI_API_KEY", "SUPBI_AI_MODEL"))
    if not (base and key and model):
        sys.exit("SUPBI_AI_* is not set; skipping")
    body = json.dumps({"model": model, "temperature": 0.4, "messages": [
        {"role": "user", "content": PROMPT + json.dumps(items, ensure_ascii=False)}]}).encode()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                  "User-Agent": "Mozilla/5.0 (bbwith-brief/1.0)", "Accept": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=240).read())
            text = r["choices"][0]["message"]["content"]
            text = re.sub(r"^.*?(\{)", r"\1", text.strip(), count=1, flags=re.S)
            text = text[:text.rfind("}") + 1]
            return json.loads(text), r.get("model", model)
        except urllib.error.HTTPError as e:
            last = e
            print("llm attempt failed:", e.code, e.read()[:300].decode("utf8", "replace"))
        except Exception as e:
            last = e
            print("llm attempt failed:", repr(e)[:200])
            time.sleep(10)
    sys.exit(f"LLM failed: {last!r}")


def validate(brief, items):
    by_id = {it["id"]: it for it in items}
    out = []
    for x in brief.get("items", []):
        srcs = [by_id[i] for i in x.get("sources", []) if isinstance(i, int) and i in by_id]
        if not srcs or not x.get("title") or not x.get("summary"):
            continue
        links = []
        for s in srcs:
            links.append({"name": s["source"], "title": s["title"], "url": s["url"]})
            if s.get("discuss") and s["discuss"] != s["url"]:
                links.append({"name": "Hacker News 讨论", "title": f"{s.get('comments_count', 0)} 条评论", "url": s["discuss"]})
        out.append({"title": strip(x["title"], 40), "summary": strip(x["summary"], 400), "take": strip(x.get("take", ""), 240),
                    "kind": x.get("kind") if x.get("kind") in ("model", "pricing", "product", "industry") else "industry",
                    "products": [p for p in x.get("products", []) if p in PRODUCTS], "links": links})
    return out


def main():
    items = collect()
    if "--dry" in sys.argv:
        print(json.dumps(items[:12], ensure_ascii=False, indent=1)[:6000])
        print(len(items), "items;", sum(len(json.dumps(i, ensure_ascii=False)) for i in items), "chars")
        return
    if len(items) < 15:
        sys.exit(f"only {len(items)} items collected; not writing")
    brief, model = ask_llm(items)
    entries = validate(brief, items)
    if len(entries) < 3:
        sys.exit(f"only {len(entries)} valid items from the LLM; not writing")
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{now.date().isoformat()}.json")
    json.dump({"date": now.date().isoformat(), "time": now.strftime("%Y-%m-%d %H:%M"), "headline": strip(brief.get("headline", ""), 60),
               "model": model, "inputs": len(items), "items": entries}, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {len(entries)} items to {path}")


if __name__ == "__main__":
    main()

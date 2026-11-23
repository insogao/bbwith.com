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
- 小标题写成一句普通读者一眼能看懂的话：谁 + 做了什么 + 对用户意味着什么，25 字以内。不要堆名词，不要用「A：B 与 C」这种罗列，英文功能名要么翻成中文、要么说清楚是什么。
  反例：「Claude 手机端改版：四标签与 Code 入口」「Gemini App 更新相机、GIF 与购物连接」
  正例：「Claude 手机 App 改版，手机上也能直接用 Claude Code 写代码」「Gemini 安卓版可以直接拍照提问，还能生成 GIF」
- 跳过对普通用户没有实际影响的猎奇项目和小众技术玩具（比如「在 DOS 里跑 AI agent」）。
- summary 讲清三件事：发生了什么、关键数字（只用输入里出现的）、对普通用户或会员用户意味着什么（例如哪档会员能用、是否免费、价格怎么变；输入没说就直接不写，也不要写「报道没有提到价格」这类话）。不要堆砌架构参数之类的技术细节。
- 语气客观克制，不夸张，不用「重磅」「炸裂」之类的词，不做推销。
- 全部用你自己的话写简体中文，不要翻译或照抄原文句子，不要引用超过 10 个字的原话。
- 只写输入里有的事实，不要补充输入以外的数字、日期或传闻；不确定的写「据报道」。
- 有 Hacker News 评论的条目，用一两句话概括社区的主要看法（好评和质疑都写），不要点名评论者。
- 每条必须在 sources 里列出支撑它的条目 id（1～4 个）。

只输出一个 JSON 对象，不要任何其他文字：
{"headline": "标题：点出今天最重要的 1～2 件具体的事，带上产品/模型名和一个关键数字或结论（如「GPT-6.2 包揽游戏榜前三，Claude Max 被算出 46 倍性价比」），28 字以内；不要用「继续」「比拼」「持续」「动态」这类空泛的词",
 "items": [{"title": "小标题：一句完整的话，谁做了什么、对用户意味着什么，25 字以内",
            "summary": "2～3 句话讲清楚发生了什么、为什么重要",
            "take": "社区怎么看，1～2 句；没有评论素材就留空字符串",
            "kind": "model | pricing | product | industry 之一",
            "products": ["只有这条新闻直接关于该产品时才填，从 chatgpt, claude, google-ai, grok, x, perplexity, cursor 里选；只是顺带提到就留空"],
            "sources": [1, 2]}]}

条目：
"""


def ask_llm(items):
    return chat(PROMPT + json.dumps(items, ensure_ascii=False), 0.4)


def chat(content, temperature):
    base, key, model = (os.environ.get(k, "") for k in ("SUPBI_AI_BASE_URL", "SUPBI_AI_API_KEY", "SUPBI_AI_MODEL"))
    if not (base and key and model):
        sys.exit("SUPBI_AI_* is not set; skipping")
    body = json.dumps({"model": model, "temperature": temperature, "messages": [
        {"role": "user", "content": content}]}).encode()
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


# ---------- fact check ----------
# A wrong price or date hurts a price site more than a missing story. Every entry is checked against the
# text of its own sources: first by the model (keep / fix / drop), then mechanically (every number it states
# must appear in a source). Entries that fail are dropped.

CHECK_PROMPT = """你是事实核查编辑。下面每条早报都附有它引用的来源原文（标题、摘要、评论）。逐条检查早报里的每个事实（数字、价格、日期、版本号、谁发布了什么、上线范围）能否在它自己的来源里找到依据。
- 都有依据：verdict 填 "ok"。
- 有个别说法来源里没有或说错了：verdict 填 "fix"，并给出改正后的 title / summary / take，只删掉或改正没依据的部分，其余保持原样，不要加入来源里没有的新信息。
- 核心事实来源里没有、或者与来源矛盾：verdict 填 "drop"。
- take（点评）是编辑观点，可以保留，但其中的事实同样要有依据。
只输出 JSON：{"checks":[{"i":序号,"verdict":"ok|fix|drop","title":"","summary":"","take":"","note":"一句话说明改了什么或为什么删"}]}

早报和来源：
"""

# money and percentages: the numbers a price site cannot afford to get wrong
MONEY = re.compile(r"(?:[$¥￥€£]|US\$|USD\s?|RMB\s?)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:%|％|美元|美金|刀|元|块|dollars?|USD)", re.I)


def numbers(text):
    out = set()
    for a, b in MONEY.findall(text or ""):
        v = (a or b).replace(",", "")
        out.add(v.rstrip("0").rstrip(".") if "." in v else v)
    return out


def src_numbers(text):
    """Every number in the sources counts as support (a price may appear there without a currency sign)."""
    return {(v.rstrip("0").rstrip(".") if "." in v else v) for v in (m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text or ""))}


def fact_check(entries, items):
    by_url = {it["url"]: it for it in items}
    packs = []
    for i, x in enumerate(entries):
        srcs = [by_url[l["url"]] for l in x["links"] if l["url"] in by_url]
        src_text = "\n".join(json.dumps({k: v for k, v in s.items() if k in ("source", "title", "desc", "text", "comments", "points", "price", "context")},
                                         ensure_ascii=False)[:1800] for s in srcs)
        x["_src"] = src_text
        packs.append({"i": i, "title": x["title"], "summary": x["summary"], "take": x["take"], "sources": src_text})
    try:
        res, _ = chat(CHECK_PROMPT + json.dumps(packs, ensure_ascii=False), 0)
        checks = {c.get("i"): c for c in res.get("checks", []) if isinstance(c, dict)}
    except SystemExit:
        raise
    except Exception as ex:  # checker unavailable: fall back to the mechanical check alone
        print("fact check LLM failed:", repr(ex)[:160])
        checks = {}
    kept, log = [], []
    for i, x in enumerate(entries):
        c = checks.get(i, {"verdict": "ok"})
        v = c.get("verdict", "ok")
        if v == "drop":
            log.append(f"drop: {x['title']} ({c.get('note', '')})")
            continue
        if v == "fix":
            for k in ("title", "summary", "take"):
                if c.get(k):
                    x[k] = strip(c[k], {"title": 40, "summary": 400, "take": 240}[k])
            log.append(f"fix: {x['title']} ({c.get('note', '')})")
        src_nums = src_numbers(x["_src"])
        missing = numbers(x["title"] + " " + x["summary"]) - src_nums
        if missing:
            log.append(f"drop (numbers not in sources {sorted(missing)[:5]}): {x['title']}")
            continue
        x.pop("_src", None)
        kept.append(x)
    for line in log:
        print("fact-check", line)
    return kept, log


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
    entries, checklog = fact_check(entries, items)
    if len(entries) < 3:
        sys.exit(f"only {len(entries)} valid items from the LLM; not writing")
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{now.date().isoformat()}.json")
    json.dump({"date": now.date().isoformat(), "time": now.strftime("%Y-%m-%d %H:%M"), "headline": strip(brief.get("headline", ""), 60),
               "model": model, "inputs": len(items), "fact_check": checklog, "items": entries}, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {len(entries)} items to {path}")


if __name__ == "__main__":
    main()

"""Scan AI / tech news feeds for price and deal news about the tracked subscriptions.

Matches are only candidates: they are opened as GitHub issues labelled "deal-candidate" for a person
(or Claude in a session) to verify against an official source before a file is added to data/deals/.

python scraper/news.py            # print new candidates, update data/news/seen.json
python scraper/news.py --issues   # also open a GitHub issue per candidate (needs GITHUB_TOKEN, GITHUB_REPOSITORY)
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN = os.path.join(ROOT, "data", "news", "seen.json")
FEEDS = [
    "https://news.sulat.com/feed/",
    "https://9to5google.com/feed/",
    "https://9to5mac.com/feed/",
    "https://blog.google/rss/",
    "https://openai.com/news/rss.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.androidauthority.com/feed/",
    "https://www.testingcatalog.com/rss/",
]
PRODUCT = re.compile(r"chatgpt|openai|codex|claude|anthropic|gemini|google (ai|one)|ai (pro|plus|ultra)|grok|supergrok|xai|"
                     r"x premium|perplexity|cursor", re.I)
DEAL = re.compile(r"\d+\s?%\s?off|discount|\bdeals?\b|black friday|cyber monday|\bsale\b|free for \d|half[- ]price|"
                  r"price (cut|drop|increase|hike)|price(s)? (go|went) (up|down)|cheaper|优惠|折扣|半价|降价|涨价", re.I)
DEAL_TITLE_ONLY = re.compile(r"pricing|new (plan|tier)|student|annual plan|price (cut|drop|increase|hike)|\bdeals?\b|\bsale\b|cheaper", re.I)
DEAL_DESC = re.compile(r"\d+\s?%\s?off|discount|black friday|cyber monday|half[- ]price|优惠|折扣|半价", re.I)
NOT_DEAL = re.compile(r"\bipo\b|stock|shares|nasdaq|valuation|funding|raises \$", re.I)
MAX_AGE_DAYS = 4


def text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
        for c in el:
            if c.tag.split("}")[-1] == n and (c.text or c.attrib.get("href")):
                return (c.text or c.attrib.get("href")).strip()
    return ""


def parse(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bbwith.com news monitor)"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    out = []
    for it in [e for e in root.iter() if e.tag.split("}")[-1] in ("item", "entry")]:
        title = html.unescape(re.sub(r"<[^>]+>", "", text(it, "title")))
        link = text(it, "link")
        if not link:
            le = next((c for c in it if c.tag.split("}")[-1] == "link"), None)
            link = le.attrib.get("href", "") if le is not None else ""
        date = text(it, "pubDate", "published", "updated")
        try:
            when = email.utils.parsedate_to_datetime(date)
        except Exception:
            try:
                when = dt.datetime.fromisoformat(date.replace("Z", "+00:00"))
            except Exception:
                when = None
        desc = html.unescape(re.sub(r"<[^>]+>", " ", text(it, "description", "summary")))[:400]
        out.append({"title": title, "link": link, "when": when, "desc": re.sub(r"\s+", " ", desc).strip(), "feed": url})
    return out


def open_issue(c):
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        return
    body = (f"**来源**：{c['feed']}\n**链接**：{c['link']}\n**发布时间**：{c['when']}\n\n> {c['desc']}\n\n"
            "这是自动筛选出的优惠/价格线索，尚未核实。核实步骤：\n"
            "1. 打开官方页面或官方账号确认优惠是否存在、适用人群、地区和截止时间\n"
            "2. 属实则在 `data/deals/` 新增一个 JSON 文件（格式见已有文件），不属实或无关则直接关闭本 Issue")
    data = json.dumps({"title": f"[优惠线索] {c['title'][:120]}", "body": body, "labels": ["deal-candidate"]}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues", data=data, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print("issue failed:", e)


def main():
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    now = dt.datetime.now(dt.timezone.utc)
    new = []
    for url in FEEDS:
        try:
            items = parse(url)
        except Exception as e:
            print("feed failed:", url, repr(e)[:120])
            continue
        for it in items:
            if not it["link"] or it["link"] in seen:
                continue
            if it["when"] and (now - it["when"].astimezone(dt.timezone.utc)).days > MAX_AGE_DAYS:
                continue
            blob = f"{it['title']} {it['desc']}"
            hit = DEAL.search(it["title"]) or DEAL_TITLE_ONLY.search(it["title"]) or DEAL_DESC.search(it["desc"])
            if PRODUCT.search(it["title"]) and hit and not NOT_DEAL.search(it["title"]):
                new.append(it)
            seen.add(it["link"])
    for c in new:
        print("CANDIDATE:", c["title"], "|", c["link"])
        if "--issues" in sys.argv:
            open_issue(c)
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    json.dump(sorted(seen)[-5000:], open(SEEN, "w"), indent=0)
    print(len(new), "new candidates")


if __name__ == "__main__":
    main()

"""Fetch the In-App Purchases list of each tracked app in every App Store storefront.

Usage:
  python scraper/crawl.py                 # crawl all apps x storefronts -> data/raw/<date>.json
  python scraper/crawl.py --probe         # re-discover valid storefronts -> scraper/storefronts.json
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from parse_iap import iaps  # noqa: E402
from plans import APPS  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def get(url):
    """Return (status, html). 301 means the storefront redirected elsewhere (does not exist)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US"})
    want = url.split("apps.apple.com/")[1].split("/")[0]
    for i in range(4):
        try:
            r = urllib.request.urlopen(req, timeout=25)
            got = r.geturl().split("apps.apple.com/")[1].split("/")[0]
            if want != got:
                return 301, ""
            return 200, r.read().decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, ""
            time.sleep(4 * (i + 1))
        except Exception:
            time.sleep(4 * (i + 1))
    return -1, ""


def job(arg):
    app, cc = arg
    st, html = get(f"https://apps.apple.com/{cc}/app/x/id{APPS[app]}?l=en-US")
    time.sleep(0.4)
    return [app, cc, st, iaps(html) if st == 200 else []]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()
    if a.probe:
        import pycountry
        tasks = [("chatgpt", c.alpha_2.lower()) for c in pycountry.countries]
    else:
        sf = json.load(open(os.path.join(HERE, "storefronts.json")))
        tasks = [(app, cc) for app in APPS for cc in sf]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(job, tasks))
    if a.probe:
        valid = sorted(r[1] for r in res if r[2] in (200, 404))
        json.dump(valid, open(os.path.join(HERE, "storefronts.json"), "w"))
        print(len(valid), "storefronts")
        return
    failed = sum(1 for r in res if r[2] == -1)
    if failed > len(res) * 0.1:
        sys.exit(f"too many failed requests: {failed}/{len(res)}")
    day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    os.makedirs(os.path.join(ROOT, "data", "raw"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "data", "raw", f"{day}.json"), "w"), ensure_ascii=False)
    fx = json.load(urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=20))
    if fx.get("result") != "success":
        sys.exit("fx fetch failed")
    json.dump(fx, open(os.path.join(ROOT, "data", "raw", f"fx-{day}.json"), "w"))
    print(day, len(res), "pages,", failed, "failed")


if __name__ == "__main__":
    main()

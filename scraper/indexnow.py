"""Tell IndexNow-enabled search engines (Bing, Yandex, Naver, Seznam...) which pages changed.

The key is public by design: https://bbwith.com/<key>.txt must return the key itself.
python scraper/indexnow.py   # submits every URL in dist/sitemap.xml
"""
import json
import os
import re
import sys
import urllib.request

KEY = "628c70b71e1aae60472fb4344fc1d459"
HOST = "bbwith.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

urls = re.findall(r"<loc>([^<]+)</loc>", open(os.path.join(ROOT, "dist", "sitemap.xml"), encoding="utf8").read())
body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt", "urlList": urls}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                             headers={"Content-Type": "application/json; charset=utf-8"})
try:
    r = urllib.request.urlopen(req, timeout=30)
    print("IndexNow", r.status, len(urls), "urls")
except urllib.error.HTTPError as e:
    print("IndexNow error", e.code, e.read()[:200])
    sys.exit(0)  # never fail the data job because of IndexNow

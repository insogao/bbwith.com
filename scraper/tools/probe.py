import os, sys, json, urllib.request, gzip
UA = {"browser": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "bot": "bbwith-news/1.0 (+https://bbwith.com/about/)"}
os.makedirs("probe", exist_ok=True)
log = {}
for i, line in enumerate(open(sys.argv[1]).read().strip().splitlines()):
    ua, url = line.split(" ", 1)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA[ua], "Accept": "*/*", "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
            if r.headers.get("Content-Encoding") == "gzip": b = gzip.decompress(b)
            log[url] = {"ua": ua, "status": r.status, "bytes": len(b), "head": b[:300].decode("utf8", "replace")}
            open(f"probe/{i:02d}.txt", "wb").write(b)
    except Exception as e:
        log[url] = {"ua": ua, "error": repr(e)[:200]}
json.dump(log, open("probe/log.json", "w"), indent=1, ensure_ascii=False)

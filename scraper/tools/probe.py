"""Fetch a list of URLs and save the responses, to inspect page structure (run in Actions)."""
import os, sys, json, urllib.request, gzip
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
os.makedirs("probe", exist_ok=True)
log = {}
for i, url in enumerate(open(sys.argv[1]).read().split()):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                                                   "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                b = gzip.decompress(b)
            log[url] = {"status": r.status, "final": r.geturl(), "bytes": len(b), "file": f"{i:02d}.html"}
            open(f"probe/{i:02d}.html", "wb").write(b)
    except Exception as e:
        log[url] = {"error": repr(e)[:300]}
json.dump(log, open("probe/log.json", "w"), indent=1)
print(json.dumps(log, indent=1))

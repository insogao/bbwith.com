"""Weekly SEO data pull through official APIs (no browser), for the weekly SEO operator.

Env:
  GTOKEN       Google access token (webmasters scope), minted keylessly by google-github-actions/auth
  BING_API_KEY Bing Webmaster API key
  CF_TOKEN     Cloudflare read-only token (Zone Read + Analytics Read)

Writes data/seo/<date>.json and data/seo/latest.json. Also re-submits the sitemap to Google.
Every source is optional: a failure is recorded under "errors" and the rest still runs.
"""
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "seo")
SITE = "https://bbwith.com/"
GSC_SITE = "sc-domain:bbwith.com"
TODAY = dt.date.today()
data = {"date": TODAY.isoformat(), "errors": {}}


def call(url, headers=None, body=None, method=None):
    req = urllib.request.Request(url, headers=headers or {}, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read()
        return json.loads(t) if t else {}


def section(name):
    def wrap(fn):
        try:
            data[name] = fn()
        except Exception as ex:  # keep going; the report says what failed
            data["errors"][name] = str(ex)[:300]
        return fn
    return wrap


def sitemap_urls():
    req = urllib.request.Request(SITE + "sitemap.xml", headers={"User-Agent": "Mozilla/5.0 (compatible; bbwith-seo-bot/1.0; +https://bbwith.com/about/)"})
    xml = urllib.request.urlopen(req, timeout=30).read().decode()
    return re.findall(r"<loc>([^<]+)</loc>", xml)


G = {"Authorization": "Bearer " + os.environ.get("GTOKEN", "")}
GS = urllib.parse.quote(GSC_SITE, safe="")


def gsc_query(days, dims, limit=50):
    end = TODAY - dt.timedelta(days=2)  # GSC data lags ~2 days
    body = {"startDate": (end - dt.timedelta(days=days - 1)).isoformat(), "endDate": end.isoformat(),
            "dimensions": dims, "rowLimit": limit}
    rows = call(f"https://www.googleapis.com/webmasters/v3/sites/{GS}/searchAnalytics/query", G, body).get("rows", [])
    return [{"keys": r.get("keys", []), "clicks": r["clicks"], "impressions": r["impressions"],
             "ctr": round(r["ctr"], 4), "position": round(r["position"], 1)} for r in rows]


if os.environ.get("GTOKEN"):
    @section("google")
    def _g():
        out = {"errors": {}}

        def part(name, fn):
            try:
                out[name] = fn()
            except Exception as ex:
                out["errors"][name] = str(ex)[:200] + " " + (getattr(ex, "read", lambda: b"")() or b"")[:200].decode("utf8", "ignore")
        for d in (7, 28):
            part(f"total_{d}d", lambda d=d: (gsc_query(d, [], 1) or [{"clicks": 0, "impressions": 0}])[0])
        part("queries_28d", lambda: gsc_query(28, ["query"], 100))
        part("pages_28d", lambda: gsc_query(28, ["page"], 100))
        part("page_query_28d", lambda: gsc_query(28, ["page", "query"], 250))
        # resubmit the sitemap so Google re-reads it this week, then record its status
        sm = urllib.parse.quote(SITE + "sitemap.xml", safe="")
        if TODAY.weekday() == 0:  # weekly is plenty for a sitemap Google already knows
            part("sitemap_submit", lambda: call(f"https://www.googleapis.com/webmasters/v3/sites/{GS}/sitemaps/{sm}", G, method="PUT") or "ok")
        part("sitemaps", lambda: call(f"https://www.googleapis.com/webmasters/v3/sites/{GS}/sitemaps", G).get("sitemap", []))
        # index status of every sitemap URL (URL Inspection API: 2,000/day quota)
        insp = {}
        try:
            urls = sitemap_urls()[:300]
        except Exception as ex:
            out["errors"]["sitemap_fetch"] = str(ex)[:200]
            urls = []
        for u in urls:
            try:
                r = call("https://searchconsole.googleapis.com/v1/urlInspection/index:inspect", G,
                         {"inspectionUrl": u, "siteUrl": GSC_SITE})["inspectionResult"]["indexStatusResult"]
                insp[u] = {k: r.get(k) for k in ("verdict", "coverageState", "lastCrawlTime", "googleCanonical", "userCanonical", "robotsTxtState", "pageFetchState")}
            except Exception as ex:
                insp[u] = {"error": str(ex)[:120]}
        out["inspection"] = insp  # noqa
        out["indexed"] = sum(1 for v in insp.values() if v.get("verdict") == "PASS")
        return out

BK = os.environ.get("BING_API_KEY", "")
if BK:
    @section("bing")
    def _b():
        def b(method, **kw):
            q = urllib.parse.urlencode({"apikey": BK, "siteUrl": SITE, **kw})
            return call(f"https://ssl.bing.com/webmaster/api.svc/json/{method}?{q}").get("d")
        out = {}
        for m in ("GetRankAndTrafficStats", "GetQueryStats", "GetPageStats", "GetCrawlIssues", "GetCrawlStats", "GetUrlSubmissionQuota"):
            try:
                v = b(m)
                out[m] = v[-60:] if isinstance(v, list) else v
            except Exception as ex:
                out[m] = {"error": str(ex)[:160]}
        return out

CF = os.environ.get("CF_TOKEN", "")
if CF:
    @section("cloudflare")
    def _c():
        h = {"Authorization": "Bearer " + CF}
        zid = call("https://api.cloudflare.com/client/v4/zones?name=bbwith.com", h)["result"][0]["id"]

        def gql(query, variables):
            r = call("https://api.cloudflare.com/client/v4/graphql", h, {"query": query, "variables": variables})
            if r.get("errors"):
                raise RuntimeError(r["errors"][0].get("message"))
            return r["data"]["viewer"]["zones"][0]
        out = {}
        daily = gql("""query($z:String!,$d:Date!){viewer{zones(filter:{zoneTag:$z}){
            httpRequests1dGroups(limit:10, filter:{date_geq:$d}){dimensions{date} sum{requests pageViews responseStatusMap{edgeResponseStatus requests}} uniq{uniques}}}}}""",
                    {"z": zid, "d": (TODAY - dt.timedelta(days=7)).isoformat()})["httpRequests1dGroups"]
        out["daily"] = [{"date": x["dimensions"]["date"], "requests": x["sum"]["requests"], "pageViews": x["sum"]["pageViews"],
                         "uniques": x["uniq"]["uniques"],
                         "status": {str(s["edgeResponseStatus"]): s["requests"] for s in x["sum"]["responseStatusMap"]}} for x in daily]
        # Cloudflare's own "nginx-ssl early hints" prefetches show up as 504s; they are not visitors, so they are filtered out.
        # last 24h by path for errors and by user agent for crawlers (adaptive datasets keep ~1 day on free plans)
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=23)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            g = gql("""query($z:String!,$t:Time!){viewer{zones(filter:{zoneTag:$z}){
                errs: httpRequestsAdaptiveGroups(limit:50, filter:{datetime_geq:$t, edgeResponseStatus_geq:500, userAgent_neq:"nginx-ssl early hints"}, orderBy:[count_DESC]){count dimensions{clientRequestPath edgeResponseStatus}}
                errwho: httpRequestsAdaptiveGroups(limit:20, filter:{datetime_geq:$t, edgeResponseStatus_geq:500, userAgent_neq:"nginx-ssl early hints"}, orderBy:[count_DESC]){count dimensions{userAgent clientCountryName datetimeHour originResponseStatus cacheStatus}}
                total: httpRequestsAdaptiveGroups(limit:20, filter:{datetime_geq:$t, userAgent_neq:"nginx-ssl early hints"}, orderBy:[count_DESC]){count dimensions{edgeResponseStatus}}
                bots: httpRequestsAdaptiveGroups(limit:40, filter:{datetime_geq:$t}, orderBy:[count_DESC]){count dimensions{userAgent}}}}}""",
                    {"z": zid, "t": since})
            out["errors_who_24h"] = [dict(x["dimensions"], n=x["count"]) for x in g["errwho"]]
            out["status_24h"] = {str(x["dimensions"]["edgeResponseStatus"]): x["count"] for x in g["total"]}
            out["errors_24h"] = [{"path": x["dimensions"]["clientRequestPath"], "status": x["dimensions"]["edgeResponseStatus"], "n": x["count"]} for x in g["errs"]]
            bots = {}
            for x in g["bots"]:
                ua = x["dimensions"]["userAgent"] or ""
                m = re.search(r"(Googlebot|bingbot|ClaudeBot|Claude-User|GPTBot|ChatGPT-User|OAI-SearchBot|PerplexityBot|Bytespider|Baiduspider|YandexBot|Applebot|meta-externalagent|CCBot|Amazonbot|DuckDuckBot)", ua, re.I)
                if m:
                    bots[m.group(1)] = bots.get(m.group(1), 0) + x["count"]
            out["crawlers_24h"] = bots
        except Exception as ex:
            out["adaptive_error"] = str(ex)[:200]
        return out

@section("site_search_gaps")
def _s():
    req = urllib.request.Request(SITE + "api/search-gaps", headers={"User-Agent": "Mozilla/5.0 (compatible; bbwith-seo-bot/1.0)"})
    return json.load(urllib.request.urlopen(req, timeout=30))


os.makedirs(OUT, exist_ok=True)
# latest.json every day (read it any time for a status report); a dated snapshot on Mondays for week-over-week comparison
for name in ([f"{TODAY.isoformat()}.json"] if TODAY.weekday() == 0 or "--snapshot" in __import__("sys").argv else []) + ["latest.json"]:
    json.dump(data, open(os.path.join(OUT, name), "w"), ensure_ascii=False, indent=1)
print("sections:", [k for k in data if k not in ("date", "errors")], "errors:", data["errors"])

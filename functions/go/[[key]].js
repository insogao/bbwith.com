// /go/<key>: outbound links with click counting.
//   /go/m<id>      -> an approved merchant listing (from D1)
//   /go/<other>    -> gift card and other links from the generated /go-map.json
import { db, today } from "../_lib.js";

let MAP = null;

export async function onRequest({ request, env, params, waitUntil }) {
  const key = (params.key || []).join("/").slice(0, 80);
  let dest = null;
  try {
    if (/^m\d+$/.test(key)) {
      const DB = await db(env);
      const l = await DB.prepare("SELECT url FROM listings WHERE id = ? AND status = 'approved'").bind(parseInt(key.slice(1), 10)).first();
      dest = l && l.url;
    } else {
      if (!MAP) MAP = await (await env.ASSETS.fetch(new URL("/go-map.json", request.url))).json();
      dest = MAP[key];
    }
  } catch (e) {
    console.error(e);
  }
  if (!dest) return Response.redirect(new URL("/", request.url).toString(), 302);
  let src = "-";
  try {
    const r = new URL(request.headers.get("referer") || "");
    if (r.host === new URL(request.url).host) src = r.pathname.slice(0, 120);
    else if (r.host) src = "ext:" + r.host;
  } catch {}
  waitUntil((async () => {
    try {
      const DB = await db(env);
      await DB.prepare(`INSERT INTO clicks (day, key, src, n) VALUES (?, ?, ?, 1) ON CONFLICT (day, key, src) DO UPDATE SET n = n + 1`)
        .bind(today(), key, src).run();
    } catch (e) { console.error(e); }
  })());
  return new Response(null, { status: 302, headers: { location: dest, "cache-control": "no-store", "x-robots-tag": "noindex, nofollow" } });
}

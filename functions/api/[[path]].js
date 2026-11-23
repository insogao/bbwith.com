import { db, json, HttpError, now, today, hashToken, ipHash, newToken, rateLimit, body, str, isAdmin, sha256 } from "../_lib.js";

const TYPES = ["topup", "account-long", "account-short", "seat", "shared", "promo"];
const PROBLEMS = ["未发货", "掉订阅", "封号", "与描述不符", "售后不处理", "其他"];
const PLAN_RX = /^[a-z0-9-]+\/[a-z0-9-]+$/;

function listingInput(x) {
  const price = Number(x.price);
  if (!(price > 0 && price < 100000)) throw new HttpError(400, "价格要填人民币数字");
  const url = str(x.url, 500, "商品链接");
  if (!/^https?:\/\//i.test(url)) throw new HttpError(400, "商品链接要以 http(s):// 开头");
  const plan_key = str(x.plan_key, 40, "档位");
  if (!PLAN_RX.test(plan_key)) throw new HttpError(400, "档位不对");
  const type = str(x.type, 20, "交付方式");
  if (!TYPES.includes(type)) throw new HttpError(400, "交付方式不对");
  const w = Math.max(0, Math.min(400, parseInt(x.warranty_days || 0, 10) || 0));
  return { title: str(x.title, 120, "商品标题"), plan_key, type, warranty_days: w, price: Math.round(price * 100) / 100, url };
}

async function merchantByToken(DB, t) {
  if (!t) throw new HttpError(401, "缺少管理链接里的密钥");
  const m = await DB.prepare("SELECT * FROM merchants WHERE token_hash = ?").bind(await hashToken(t)).first();
  if (!m) throw new HttpError(401, "管理密钥无效");
  if (m.status !== "active") throw new HttpError(403, "该商家已被停用");
  return m;
}

async function publicListings(DB) {
  const ls = (await DB.prepare(`SELECT l.id, l.merchant_id, m.name AS merchant, l.title, l.plan_key, l.type, l.warranty_days, l.price, l.url,
      l.created_at, l.updated_at, l.approved_at, l.manual_verified_at FROM listings l JOIN merchants m ON m.id = l.merchant_id
      WHERE l.status = 'approved' AND m.status = 'active' ORDER BY l.id`).all()).results;
  const cs = (await DB.prepare(`SELECT id, listing_id, merchant_id, problem, detail, published_at, reply, reply_at, resolved
      FROM complaints WHERE status = 'published' ORDER BY published_at DESC LIMIT 2000`).all()).results;
  const vs = (await DB.prepare(`SELECT target, SUM(v = 1) AS up, SUM(v = -1) AS down FROM votes WHERE target LIKE 'listing:%' GROUP BY target`).all()).results;
  const votes = Object.fromEntries(vs.map((v) => [v.target.slice(8), { up: v.up, down: v.down }]));
  return { time: now(), listings: ls.map((l) => ({ ...l, votes: votes[l.id] || { up: 0, down: 0 } })), complaints: cs };
}

const routes = {
  // ---- public ----
  "GET listings": async ({ DB }) => json(await publicListings(DB), 200, { "cache-control": "public, max-age=60" }),

  "GET votes": async ({ DB, url, request, env }) => {
    const targets = (url.searchParams.get("targets") || "").split(",").filter(Boolean).slice(0, 50);
    if (!targets.length) return json({});
    const ip = await ipHash(request, env);
    const q = targets.map(() => "?").join(",");
    const agg = (await DB.prepare(`SELECT target, SUM(v = 1) AS up, SUM(v = -1) AS down FROM votes WHERE target IN (${q}) GROUP BY target`)
      .bind(...targets).all()).results;
    const mine = (await DB.prepare(`SELECT target, v FROM votes WHERE ip_hash = ? AND target IN (${q})`).bind(ip, ...targets).all()).results;
    const out = Object.fromEntries(targets.map((t) => [t, { up: 0, down: 0, mine: 0 }]));
    agg.forEach((a) => Object.assign(out[a.target], { up: a.up, down: a.down }));
    mine.forEach((m) => (out[m.target].mine = m.v));
    return json(out);
  },

  "POST vote": async ({ DB, request, env }) => {
    const b = await body(request);
    const target = str(b.target, 80, "目标");
    if (!/^(listing|brief|deal|plan|gift):[\w:./-]+$/.test(target)) throw new HttpError(400, "目标不对");
    const v = [1, -1, 0].includes(b.v) ? b.v : 0;
    const ip = await ipHash(request, env);
    await rateLimit(DB, ip, "vote", 300);
    if (v === 0) await DB.prepare("DELETE FROM votes WHERE target = ? AND ip_hash = ?").bind(target, ip).run();
    else await DB.prepare(`INSERT INTO votes (target, ip_hash, v, at) VALUES (?, ?, ?, ?)
        ON CONFLICT (target, ip_hash) DO UPDATE SET v = excluded.v, at = excluded.at`).bind(target, ip, v, now()).run();
    const a = await DB.prepare("SELECT SUM(v = 1) AS up, SUM(v = -1) AS down FROM votes WHERE target = ?").bind(target).first();
    return json({ up: a.up || 0, down: a.down || 0, mine: v });
  },

  "POST pv": async ({ DB, request }) => {
    const b = await request.text();
    const path = (b || "/").slice(0, 120).split("?")[0];
    if (!path.startsWith("/")) return json({});
    await DB.prepare(`INSERT INTO pv (day, path, n) VALUES (?, ?, 1) ON CONFLICT (day, path) DO UPDATE SET n = n + 1`).bind(today(), path).run();
    return json({});
  },

  // batched behaviour events from assets/app.js; everything is stored as daily counts
  "POST ev": async ({ DB, request, env }) => {
    let b;
    try { b = JSON.parse(await request.text()); } catch { return json({}); }
    const list = (Array.isArray(b.e) ? b.e : []).slice(0, 30);
    if (!list.length) return json({});
    const ip = await ipHash(request, env);
    try { await rateLimit(DB, ip, "ev", 800); } catch { return json({}); }
    const day = today();
    const clean = (v, n) => String(v ?? "").replace(/[\u0000-\u001f]/g, "").trim().slice(0, n);
    const vid = /^[a-f0-9]{16,32}$/.test(b.v || "") ? (await sha256("vid:" + b.v)).slice(0, 24) : null;
    const st = [];
    for (const e of list) {
      const path = clean(e.p, 120).split("?")[0];
      if (!path.startsWith("/") || /^\/(admin|merchant\/manage)/.test(path)) continue;
      if (e.t === "view") {
        st.push(DB.prepare(`INSERT INTO pv (day, path, n) VALUES (?, ?, 1) ON CONFLICT (day, path) DO UPDATE SET n = n + 1`).bind(day, path));
        if (vid) {
          st.push(DB.prepare(`INSERT INTO visitors (vid, first_day) VALUES (?, ?) ON CONFLICT (vid) DO NOTHING`).bind(vid, day));
          st.push(DB.prepare(`INSERT INTO visits (day, vid, views) VALUES (?, ?, 1) ON CONFLICT (day, vid) DO UPDATE SET views = views + 1`).bind(day, vid));
        }
        const host = clean(e.r, 60).toLowerCase();
        if (host) st.push(DB.prepare(`INSERT INTO ev_ref (day, host, n) VALUES (?, ?, 1) ON CONFLICT (day, host) DO UPDATE SET n = n + 1`).bind(day, host));
      } else if (e.t === "click") {
        const sec = clean(e.s, 30) || "page", label = clean(e.l, 40) || "-";
        st.push(DB.prepare(`INSERT INTO ev_click (day, path, sec, label, n) VALUES (?, ?, ?, ?, 1)
            ON CONFLICT (day, path, sec, label) DO UPDATE SET n = n + 1`).bind(day, path, sec, label));
      } else if (e.t === "engage") {
        const ms = Math.max(0, Math.min(parseInt(e.ms, 10) || 0, 3600e3)), sc = Math.max(0, Math.min(parseInt(e.sc, 10) || 0, 100));
        const sec = ms / 1000;
        st.push(DB.prepare(`INSERT INTO ev_engage (day, path, n, ms, t10, t30, t120, tmore, s25, s50, s75, s100)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (day, path) DO UPDATE SET n = n + 1, ms = ms + excluded.ms, t10 = t10 + excluded.t10, t30 = t30 + excluded.t30,
              t120 = t120 + excluded.t120, tmore = tmore + excluded.tmore, s25 = s25 + excluded.s25, s50 = s50 + excluded.s50,
              s75 = s75 + excluded.s75, s100 = s100 + excluded.s100`)
          .bind(day, path, ms, +(sec < 10), +(sec >= 10 && sec < 30), +(sec >= 30 && sec < 120), +(sec >= 120),
                +(sc >= 25), +(sc >= 50), +(sc >= 75), +(sc >= 95)));
      } else if (e.t === "search") {
        const q = clean(e.q, 40).toLowerCase();
        if (q) st.push(DB.prepare(`INSERT INTO ev_search (day, q, n, zero) VALUES (?, ?, 1, ?)
            ON CONFLICT (day, q) DO UPDATE SET n = n + 1, zero = zero + excluded.zero`).bind(day, q, +(parseInt(e.n, 10) === 0)));
      }
    }
    if (st.length) await DB.batch(st);
    return json({});
  },

  // public, aggregated only: searches that found nothing, asked at least twice in 28 days (read by scraper/seo_data.py)
  "GET search-gaps": async ({ DB }) => {
    const since = new Date(Date.now() + 8 * 3600e3 - 27 * 86400e3).toISOString().slice(0, 10);
    const r = await DB.prepare(`SELECT q, SUM(n) AS n, SUM(zero) AS zero FROM ev_search WHERE day >= ? GROUP BY q
        HAVING SUM(zero) >= 2 AND LENGTH(q) <= 20 ORDER BY zero DESC LIMIT 50`).bind(since).all();
    return json({ since, gaps: r.results }, 200, { "cache-control": "public, max-age=3600" });
  },

  "GET admin/behaviour": async ({ DB, url }) => {
    const q = (s, ...a) => DB.prepare(s).bind(...a).all().then((r) => r.results);
    const days = Math.min(parseInt(url.searchParams.get("days"), 10) || 30, 90);
    const since = new Date(Date.now() + 8 * 3600e3 - (days - 1) * 86400e3).toISOString().slice(0, 10);
    return json({
      days,
      visitors: await q(`SELECT v.day, COUNT(*) AS visitors, SUM(f.first_day = v.day) AS new, SUM(f.first_day < v.day) AS returning,
          SUM(v.views) AS views FROM visits v JOIN visitors f ON f.vid = v.vid WHERE v.day >= ? GROUP BY v.day ORDER BY v.day`, since),
      engage: await q(`SELECT path, SUM(n) AS n, SUM(ms) / MAX(SUM(n), 1) AS avg_ms, SUM(t10) AS t10, SUM(t30) AS t30, SUM(t120) AS t120,
          SUM(tmore) AS tmore, SUM(s25) AS s25, SUM(s50) AS s50, SUM(s75) AS s75, SUM(s100) AS s100
          FROM ev_engage WHERE day >= ? GROUP BY path ORDER BY n DESC LIMIT 60`, since),
      sections: await q(`SELECT sec, SUM(n) AS n FROM ev_click WHERE day >= ? GROUP BY sec ORDER BY n DESC LIMIT 40`, since),
      clicks: await q(`SELECT path, sec, label, SUM(n) AS n FROM ev_click WHERE day >= ? GROUP BY path, sec, label ORDER BY n DESC LIMIT 100`, since),
      searches: await q(`SELECT q, SUM(n) AS n, SUM(zero) AS zero FROM ev_search WHERE day >= ? GROUP BY q ORDER BY n DESC LIMIT 60`, since),
      refs: await q(`SELECT host, SUM(n) AS n FROM ev_ref WHERE day >= ? GROUP BY host ORDER BY n DESC LIMIT 40`, since),
    });
  },

  "POST complaint": async ({ DB, request, env }) => {
    const b = await body(request);
    const ip = await ipHash(request, env);
    await rateLimit(DB, ip, "complaint", 3);
    const l = await DB.prepare("SELECT id, merchant_id FROM listings WHERE id = ? AND status = 'approved'").bind(parseInt(b.listing_id, 10) || 0).first();
    if (!l) throw new HttpError(404, "找不到这个商品");
    const problem = str(b.problem, 20, "问题类型");
    if (!PROBLEMS.includes(problem)) throw new HttpError(400, "问题类型不对");
    await DB.prepare(`INSERT INTO complaints (listing_id, merchant_id, problem, detail, order_ref, contact, created_at, ip_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).bind(l.id, l.merchant_id, problem, str(b.detail, 1000, "问题经过"),
      str(b.order_ref, 200, "订单凭证"), str(b.contact, 100, "联系方式", false), now(), ip).run();
    return json({ ok: true });
  },

  // ---- merchants ----
  "POST merchant/submit": async ({ DB, request, env }) => {
    const b = await body(request);
    const ip = await ipHash(request, env);
    await rateLimit(DB, ip, "submit", 5);
    if (!b.agree) throw new HttpError(400, "请先同意入驻须知");
    const items = (Array.isArray(b.listings) ? b.listings : []).slice(0, 20).map(listingInput);
    if (!items.length) throw new HttpError(400, "至少填写一个商品");
    const token = newToken();
    const t = now();
    const m = await DB.prepare("INSERT INTO merchants (name, contact, token_hash, created_at) VALUES (?, ?, ?, ?) RETURNING id")
      .bind(str(b.name, 40, "店铺名称"), str(b.contact, 100, "联系方式"), await hashToken(token), t).first();
    await DB.batch(items.map((x) => DB.prepare(`INSERT INTO listings (merchant_id, title, plan_key, type, warranty_days, price, url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).bind(m.id, x.title, x.plan_key, x.type, x.warranty_days, x.price, x.url, t, t)));
    return json({ ok: true, merchant_id: m.id, token });
  },

  "GET merchant/me": async ({ DB, url }) => {
    const m = await merchantByToken(DB, url.searchParams.get("t"));
    const ls = (await DB.prepare("SELECT * FROM listings WHERE merchant_id = ? AND status != 'removed' ORDER BY id").bind(m.id).all()).results;
    const cs = (await DB.prepare(`SELECT id, listing_id, problem, detail, published_at, reply, reply_at, resolved FROM complaints
        WHERE merchant_id = ? AND status = 'published' ORDER BY id DESC`).bind(m.id).all()).results;
    return json({ merchant: { id: m.id, name: m.name, contact: m.contact }, listings: ls, complaints: cs });
  },

  "POST merchant/listing": async ({ DB, request }) => {
    const b = await body(request);
    const m = await merchantByToken(DB, b.t);
    const t = now();
    if (b.id) {
      const l = await DB.prepare("SELECT * FROM listings WHERE id = ? AND merchant_id = ?").bind(b.id, m.id).first();
      if (!l) throw new HttpError(404, "找不到这个商品");
      if (b.remove) {
        await DB.prepare("UPDATE listings SET status = 'removed', updated_at = ? WHERE id = ?").bind(t, l.id).run();
        return json({ ok: true });
      }
      const x = listingInput(b);
      // a new link or product needs review again; a price change is re-checked by the crawler
      const review = x.url !== l.url || x.plan_key !== l.plan_key || x.type !== l.type;
      await DB.prepare(`UPDATE listings SET title = ?, plan_key = ?, type = ?, warranty_days = ?, price = ?, url = ?, updated_at = ?,
          manual_verified_at = NULL, status = CASE WHEN ? THEN 'pending' ELSE status END WHERE id = ?`)
        .bind(x.title, x.plan_key, x.type, x.warranty_days, x.price, x.url, t, review ? 1 : 0, l.id).run();
      return json({ ok: true, review });
    }
    const n = await DB.prepare("SELECT COUNT(*) AS n FROM listings WHERE merchant_id = ? AND status != 'removed'").bind(m.id).first();
    if (n.n >= 30) throw new HttpError(400, "每家最多 30 个商品");
    const x = listingInput(b);
    await DB.prepare(`INSERT INTO listings (merchant_id, title, plan_key, type, warranty_days, price, url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).bind(m.id, x.title, x.plan_key, x.type, x.warranty_days, x.price, x.url, t, t).run();
    return json({ ok: true, review: true });
  },

  "POST merchant/reply": async ({ DB, request }) => {
    const b = await body(request);
    const m = await merchantByToken(DB, b.t);
    const r = await DB.prepare("UPDATE complaints SET reply = ?, reply_at = ? WHERE id = ? AND merchant_id = ? AND status = 'published'")
      .bind(str(b.reply, 800, "回复"), now(), b.id, m.id).run();
    if (!r.meta.changes) throw new HttpError(404, "找不到这条投诉");
    return json({ ok: true });
  },

  // ---- admin ----
  "GET admin/overview": async ({ DB }) => {
    const q = (s, ...a) => DB.prepare(s).bind(...a).all().then((r) => r.results);
    const since = new Date(Date.now() + 8 * 3600e3 - 29 * 86400e3).toISOString().slice(0, 10);
    return json({
      pending: await q(`SELECT l.*, m.name AS merchant, m.contact FROM listings l JOIN merchants m ON m.id = l.merchant_id
          WHERE l.status = 'pending' ORDER BY l.id`),
      listings: await q(`SELECT l.*, m.name AS merchant, m.status AS merchant_status FROM listings l JOIN merchants m ON m.id = l.merchant_id
          WHERE l.status = 'approved' ORDER BY l.plan_key, l.price`),
      complaints: await q(`SELECT c.*, l.title, m.name AS merchant FROM complaints c JOIN listings l ON l.id = c.listing_id
          JOIN merchants m ON m.id = c.merchant_id WHERE c.status IN ('pending', 'published') ORDER BY c.status DESC, c.id DESC LIMIT 200`),
      clicks: await q("SELECT key, SUM(n) AS n FROM clicks WHERE day >= ? GROUP BY key ORDER BY n DESC LIMIT 100", since),
      click_src: await q("SELECT src, SUM(n) AS n FROM clicks WHERE day >= ? GROUP BY src ORDER BY n DESC LIMIT 100", since),
      pv: await q("SELECT path, SUM(n) AS n FROM pv WHERE day >= ? GROUP BY path ORDER BY n DESC LIMIT 100", since),
      daily: await q(`SELECT d.day, d.pv, IFNULL(c.clicks, 0) AS clicks FROM (SELECT day, SUM(n) AS pv FROM pv WHERE day >= ? GROUP BY day) d
          LEFT JOIN (SELECT day, SUM(n) AS clicks FROM clicks WHERE day >= ? GROUP BY day) c ON c.day = d.day ORDER BY d.day`, since, since),
    });
  },

  "POST admin/listing": async ({ DB, request }) => {
    const b = await body(request);
    const t = now();
    const set = {
      approve: ["status = 'approved', approved_at = ?, note = ?", [t, b.note || null]],
      reject: ["status = 'rejected', note = ?", [b.note || null]],
      verify: ["manual_verified_at = ?", [t]],
      edit: ["type = ?, plan_key = ?, warranty_days = ?", [b.type, b.plan_key, parseInt(b.warranty_days, 10) || 0]],
      remove: ["status = 'removed', note = ?", [b.note || null]],
    }[b.action];
    if (!set) throw new HttpError(400, "未知操作");
    if (b.action === "edit" && (!TYPES.includes(b.type) || !PLAN_RX.test(b.plan_key || ""))) throw new HttpError(400, "档位或交付方式不对");
    await DB.prepare(`UPDATE listings SET ${set[0]}, updated_at = ? WHERE id = ?`).bind(...set[1], t, b.id).run();
    return json({ ok: true });
  },

  "POST admin/complaint": async ({ DB, request }) => {
    const b = await body(request);
    const t = now();
    const set = { publish: ["status = 'published', published_at = ?", [t]], reject: ["status = 'rejected'", []],
                  resolve: ["resolved = 1", []], unresolve: ["resolved = 0", []] }[b.action];
    if (!set) throw new HttpError(400, "未知操作");
    await DB.prepare(`UPDATE complaints SET ${set[0]} WHERE id = ?`).bind(...set[1], b.id).run();
    return json({ ok: true });
  },

  "POST admin/merchant": async ({ DB, request }) => {
    const b = await body(request);
    if (!["active", "banned"].includes(b.status)) throw new HttpError(400, "状态不对");
    await DB.prepare("UPDATE merchants SET status = ? WHERE id = ?").bind(b.status, b.id).run();
    return json({ ok: true });
  },
};

export async function onRequest(ctx) {
  const { request, env, params } = ctx;
  const path = (params.path || []).join("/");
  const route = routes[`${request.method} ${path}`];
  try {
    if (!route) throw new HttpError(404, "没有这个接口");
    if (path.startsWith("admin/") && !(await isAdmin(request, env))) throw new HttpError(401, "需要管理员密钥");
    const DB = await db(env);
    return await route({ DB, request, env, url: new URL(request.url) });
  } catch (e) {
    if (e instanceof HttpError) return json({ error: e.message }, e.status);
    console.error(e);
    return json({ error: "服务器出错了，请稍后再试" }, 500);
  }
}

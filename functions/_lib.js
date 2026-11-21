// Shared helpers for Pages Functions. D1 binding: env.DB. Secrets: env.ADMIN_TOKEN (optional env.IP_SALT).

export const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS merchants (id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT, token_hash TEXT NOT NULL,
     created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active')`,
  `CREATE TABLE IF NOT EXISTS listings (id INTEGER PRIMARY KEY, merchant_id INTEGER NOT NULL, title TEXT NOT NULL, plan_key TEXT NOT NULL,
     type TEXT NOT NULL, warranty_days INTEGER NOT NULL DEFAULT 0, price REAL NOT NULL, url TEXT NOT NULL,
     status TEXT NOT NULL DEFAULT 'pending', note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
     approved_at TEXT, manual_verified_at TEXT)`,
  `CREATE TABLE IF NOT EXISTS complaints (id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL, merchant_id INTEGER NOT NULL,
     problem TEXT NOT NULL, detail TEXT NOT NULL, order_ref TEXT NOT NULL, contact TEXT, status TEXT NOT NULL DEFAULT 'pending',
     created_at TEXT NOT NULL, published_at TEXT, reply TEXT, reply_at TEXT, resolved INTEGER NOT NULL DEFAULT 0, ip_hash TEXT)`,
  `CREATE TABLE IF NOT EXISTS votes (target TEXT NOT NULL, ip_hash TEXT NOT NULL, v INTEGER NOT NULL, at TEXT NOT NULL,
     PRIMARY KEY (target, ip_hash))`,
  `CREATE TABLE IF NOT EXISTS clicks (day TEXT NOT NULL, key TEXT NOT NULL, src TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
     PRIMARY KEY (day, key, src))`,
  `CREATE TABLE IF NOT EXISTS pv (day TEXT NOT NULL, path TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, path))`,
  `CREATE TABLE IF NOT EXISTS ratelimit (ip_hash TEXT NOT NULL, action TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
     PRIMARY KEY (ip_hash, action, day))`,
  `CREATE INDEX IF NOT EXISTS listings_status ON listings (status)`,
  `CREATE INDEX IF NOT EXISTS complaints_listing ON complaints (listing_id, status)`,
];

let ready = false;
export async function db(env) {
  if (!env.DB) throw new HttpError(503, "数据库未配置");
  if (!ready) {
    await env.DB.batch(SCHEMA.map((s) => env.DB.prepare(s)));
    ready = true;
  }
  return env.DB;
}

export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

export const now = () => new Date().toISOString().slice(0, 19) + "Z";
// Beijing date, so daily stats line up with the rest of the site
export const today = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);

async function sha256(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}
export const hashToken = (t) => sha256("token:" + t);
export async function ipHash(request, env) {
  const ip = request.headers.get("cf-connecting-ip") || "0.0.0.0";
  return (await sha256((env.IP_SALT || env.ADMIN_TOKEN || "bbwith") + ":" + ip)).slice(0, 32);
}
export function newToken() {
  const a = new Uint8Array(24);
  crypto.getRandomValues(a);
  return [...a].map((x) => x.toString(16).padStart(2, "0")).join("");
}

// at most `limit` actions of this kind per IP per day
export async function rateLimit(DB, ip, action, limit) {
  const day = today();
  const r = await DB.prepare(`INSERT INTO ratelimit (ip_hash, action, day, n) VALUES (?, ?, ?, 1)
      ON CONFLICT (ip_hash, action, day) DO UPDATE SET n = n + 1 RETURNING n`).bind(ip, action, day).first();
  if (r.n > limit) throw new HttpError(429, "今天提交次数太多了，请明天再试");
}

export async function body(request) {
  try { return await request.json(); } catch { throw new HttpError(400, "请求格式不对"); }
}

export function str(v, max, name, required = true) {
  const s = (v ?? "").toString().trim();
  if (required && !s) throw new HttpError(400, `请填写${name}`);
  if (s.length > max) throw new HttpError(400, `${name}太长了（最多 ${max} 字）`);
  return s;
}

// Admin = a request that passed Cloudflare Access (Google / email login), verified by its signed JWT.
// env.ACCESS_TEAM: e.g. "bbwith" for bbwith.cloudflareaccess.com; env.ACCESS_AUD: the application's AUD tag;
// env.ADMIN_EMAILS: comma-separated allowed emails. ADMIN_TOKEN still works as a fallback if it is set.
// Not secrets: the Access team name, the application's AUD tag and the admin email.
const ACCESS = { team: "gavinni", aud: "c0ef962fda851815269dd9f288c51846e7a050c7886a98b72ecdd486f105ba45", emails: "insogao@gmail.com" };
let certs = null, certsAt = 0;
function b64url(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(s + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
async function accessEmail(request, env) {
  const jwt = request.headers.get("cf-access-jwt-assertion") ||
    (request.headers.get("cookie") || "").match(/CF_Authorization=([^;]+)/)?.[1];
  const team = env.ACCESS_TEAM || ACCESS.team, audTag = env.ACCESS_AUD || ACCESS.aud;
  if (!jwt) return null;
  const [h, p, sig] = jwt.split(".");
  if (!sig) return null;
  const header = JSON.parse(new TextDecoder().decode(b64url(h)));
  const claims = JSON.parse(new TextDecoder().decode(b64url(p)));
  if (Date.now() - certsAt > 3600e3 || !certs) {
    certs = (await (await fetch(`https://${team}.cloudflareaccess.com/cdn-cgi/access/certs`)).json()).keys;
    certsAt = Date.now();
  }
  const jwk = certs.find((k) => k.kid === header.kid);
  if (!jwk) return null;
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64url(sig), new TextEncoder().encode(h + "." + p));
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!ok || !aud.includes(audTag) || claims.exp * 1000 < Date.now()) return null;
  return (claims.email || "").toLowerCase();
}

export async function isAdmin(request, env) {
  const t = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (env.ADMIN_TOKEN && t && t === env.ADMIN_TOKEN) return true;
  try {
    const email = await accessEmail(request, env);
    const allowed = (env.ADMIN_EMAILS || ACCESS.emails).toLowerCase().split(",").map((x) => x.trim()).filter(Boolean);
    return !!email && allowed.includes(email);
  } catch (e) {
    console.error(e);
    return false;
  }
}

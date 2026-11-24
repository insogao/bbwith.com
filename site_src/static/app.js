// bbwith: behaviour stats, up/down votes, merchant / complaint / admin forms. No framework, no cookies.
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }
  function api(path, opts) {
    opts = opts || {};
    var h = { "content-type": "application/json" };
    if (opts.admin) h.authorization = "Bearer " + (localStorage.getItem("bbwith-admin") || "");
    return fetch("/api/" + path, { method: opts.body ? "POST" : "GET", headers: h, body: opts.body ? JSON.stringify(opts.body) : undefined })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); });
  }
  window.bbApi = api; window.bbEsc = esc;

  // ---- behaviour stats: page view, time on page, scroll depth, clicks by section, searches ----
  // No cookies. A random id kept in this browser (localStorage) tells new from returning visitors; it is hashed on the server.
  var EV = (function () {
    var off = /^\/(admin|merchant\/manage)/.test(location.pathname) || !navigator.sendBeacon;
    var q = [], vid = "";
    try {
      vid = localStorage.getItem("bbwith-vid") || "";
      if (!/^[a-f0-9]{16,32}$/.test(vid)) {
        var a = new Uint8Array(12); crypto.getRandomValues(a);
        vid = Array.prototype.map.call(a, function (b) { return (b < 16 ? "0" : "") + b.toString(16); }).join("");
        localStorage.setItem("bbwith-vid", vid);
      }
    } catch (e) { vid = ""; }
    function flush() {
      if (off || !q.length) return;
      try { navigator.sendBeacon("/api/ev", JSON.stringify({ v: vid, e: q.splice(0, 30) })); } catch (e) {}
    }
    function push(ev) { if (off) return; ev.p = location.pathname; q.push(ev); if (q.length >= 10) flush(); }
    setInterval(flush, 8000);
    // visible time and how far down the page the reader got
    var shown = document.visibilityState === "visible" ? Date.now() : 0, ms = 0, maxSc = 0, sent = false;
    function scroll() {
      var h = document.documentElement.scrollHeight - innerHeight;
      var sc = h <= 0 ? 100 : Math.round(scrollY / h * 100);
      if (sc > maxSc) maxSc = sc;
    }
    addEventListener("scroll", scroll, { passive: true });
    function hide() {
      if (shown) { ms += Date.now() - shown; shown = 0; }
      if (!sent && ms > 300) { push({ t: "engage", ms: ms, sc: maxSc }); sent = true; }
      flush();
    }
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") hide(); else shown = Date.now();
    });
    addEventListener("pagehide", hide);
    // which block a click came from: the nearest [data-sec], else the nearest id, else the page
    document.addEventListener("click", function (ev) {
      var el = ev.target.closest && ev.target.closest("a,button,summary,select,[data-pf]");
      if (!el) return;
      var box = el.closest("[data-sec]");
      var sec = box ? box.getAttribute("data-sec") : heading(el);
      var label = el.getAttribute("data-ev") || (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40) || el.getAttribute("href") || el.tagName;
      push({ t: "click", s: sec, l: label });
    }, true);
    // no explicit block: name it after the nearest heading above the click, e.g. "公开店铺报价"
    function heading(el) {
      for (var n = el; n && n !== document.body; n = n.parentElement) {
        if (/^H[12]$/.test(n.tagName)) return n.textContent.split(/[（(：:]/)[0].trim().slice(0, 30);
        for (var p = n.previousElementSibling; p; p = p.previousElementSibling) {
          if (/^H[12]$/.test(p.tagName)) return p.textContent.split(/[（(：:]/)[0].trim().slice(0, 30);
        }
      }
      return "页面其他";
    }
    var ref = "";
    try { var r = document.referrer ? new URL(document.referrer).hostname : ""; if (r && r !== location.hostname) ref = r.replace(/^www\./, ""); } catch (e) {}
    push({ t: "view", r: ref });
    scroll();
    return { push: push };
  })();
  window.bbEv = EV;

  // votes: <span class="vote" data-target="listing:12"></span>
  var boxes = $$(".vote[data-target]");
  function paint(box, s) {
    var n = function (x) { return x ? " <b>" + x + "</b>" : ""; };  // no "0" counters
    box.innerHTML = '<button type="button" data-v="1" class="' + (s.mine === 1 ? "on" : "") + '" title="有用">👍' + n(s.up) +
      '</button><button type="button" data-v="-1" class="' + (s.mine === -1 ? "on" : "") + '" title="不靠谱">👎' + n(s.down) + "</button>";
    box._s = s;
  }
  if (boxes.length) {
    boxes.forEach(function (b) { paint(b, { up: 0, down: 0, mine: 0 }); });
    var ts = boxes.map(function (b) { return b.dataset.target; });
    for (var i = 0; i < ts.length; i += 50) {
      api("votes?targets=" + encodeURIComponent(ts.slice(i, i + 50).join(","))).then(function (j) {
        boxes.forEach(function (b) { if (j[b.dataset.target]) paint(b, j[b.dataset.target]); });
      }).catch(function () {});
    }
    document.addEventListener("click", function (ev) {
      var btn = ev.target.closest(".vote button");
      if (!btn) return;
      var box = btn.parentNode, v = parseInt(btn.dataset.v, 10);
      if (box._s && box._s.mine === v) v = 0;
      api("vote", { body: { target: box.dataset.target, v: v } }).then(function (s) { paint(box, s); })
        .catch(function (e) { alert(e.message); });
    });
  }

  // ---- merchant join form ----
  var join = $("#join-form");
  if (join) {
    var tpl = $("#listing-row");
    var add = function () { $("#rows").appendChild(tpl.content.cloneNode(true)); };
    add();
    $("#add-row").onclick = add;
    join.addEventListener("click", function (ev) { if (ev.target.classList.contains("del-row")) ev.target.closest(".row").remove(); });
    join.onsubmit = function (ev) {
      ev.preventDefault();
      var f = new FormData(join);
      var ls = $$(".row", join).map(function (r) {
        var o = {}; $$("[name]", r).forEach(function (i) { o[i.name] = i.value; }); return o;
      });
      $("#join-msg").textContent = "提交中…";
      api("merchant/submit", { body: { name: f.get("name"), contact: f.get("contact"), agree: !!f.get("agree"), listings: ls } })
        .then(function (j) {
          var link = location.origin + "/merchant/manage/#t=" + j.token;
          join.hidden = true;
          $("#join-done").hidden = false;
          $("#manage-link").value = link;
          $("#manage-open").href = link;
        }).catch(function (e) { $("#join-msg").textContent = "提交失败：" + e.message; });
    };
  }

  // ---- merchant manage ----
  var mg = $("#manage");
  if (mg) {
    var t = (location.hash.match(/t=([0-9a-f]+)/) || [])[1] || sessionStorage.getItem("bbwith-mt");
    if (!t) { mg.innerHTML = "<p>请从入驻时拿到的管理链接打开本页。</p>"; return; }
    sessionStorage.setItem("bbwith-mt", t);
    history.replaceState(null, "", location.pathname);
    var STATUS = { pending: "审核中", approved: "已上架", rejected: "未通过" };
    var load = function () {
      api("merchant/me?t=" + t).then(function (j) {
        var plans = $("#plan-options").innerHTML, types = $("#type-options").innerHTML;
        var row = function (l) {
          return '<form class="row" data-id="' + (l.id || "") + '"><div class="grid">' +
            '<label>商品标题<input name="title" value="' + esc(l.title) + '" required></label>' +
            '<label>档位<select name="plan_key">' + plans + "</select></label>" +
            '<label>交付方式<select name="type">' + types + "</select></label>" +
            '<label>质保天数<input name="warranty_days" type="number" min="0" value="' + esc(l.warranty_days || 0) + '"></label>' +
            '<label>售价（元）<input name="price" type="number" step="0.01" min="0.01" value="' + esc(l.price || "") + '" required></label>' +
            '<label class="wide">商品链接<input name="url" type="url" value="' + esc(l.url || "") + '" required></label></div>' +
            '<p class="small">' + (l.id ? "状态：" + (STATUS[l.status] || l.status) + (l.note ? "（" + esc(l.note) + "）" : "") : "新商品") +
            ' <button class="btn small">保存</button>' + (l.id ? ' <button type="button" class="btn small ghost del">下架</button>' : "") + "</p></form>";
        };
        mg.innerHTML = "<h2>" + esc(j.merchant.name) + " 的商品</h2>" + j.listings.map(row).join("") +
          '<h3>新增商品</h3>' + row({}) +
          "<h2>收到的投诉</h2>" + (j.complaints.length ? j.complaints.map(function (c) {
            return '<div class="complaint"><p><b>' + esc(c.problem) + "</b> · 商品 #" + c.listing_id + " · " + esc((c.published_at || "").slice(0, 10)) +
              (c.resolved ? " · 已解决" : "") + "</p><p>" + esc(c.detail) + '</p><form class="reply" data-id="' + c.id +
              '"><textarea name="reply" rows="2" placeholder="公开回复">' + esc(c.reply || "") + '</textarea><button class="btn small">回复</button></form></div>';
          }).join("") : "<p>暂无公开投诉。</p>");
        $$("form.row", mg).forEach(function (f, i) {
          var l = j.listings[i] || {};
          if (l.plan_key) f.plan_key.value = l.plan_key;
          if (l.type) f.type.value = l.type;
        });
      }).catch(function (e) { mg.innerHTML = "<p>加载失败：" + esc(e.message) + "</p>"; });
    };
    mg.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var f = ev.target, b = { t: t };
      if (f.classList.contains("reply")) {
        api("merchant/reply", { body: { t: t, id: +f.dataset.id, reply: f.reply.value } }).then(function () { alert("已回复"); load(); })
          .catch(function (e) { alert(e.message); });
        return;
      }
      $$("[name]", f).forEach(function (i) { b[i.name] = i.value; });
      if (f.dataset.id) b.id = +f.dataset.id;
      api("merchant/listing", { body: b }).then(function (r) { alert(r.review ? "已保存，需要重新审核" : "已保存，价格会在下次自动核价时更新"); load(); })
        .catch(function (e) { alert(e.message); });
    });
    mg.addEventListener("click", function (ev) {
      if (!ev.target.classList.contains("del")) return;
      if (!confirm("确定下架这个商品？")) return;
      api("merchant/listing", { body: { t: t, id: +ev.target.closest("form").dataset.id, remove: true } }).then(load);
    });
    load();
  }

  // ---- complaint form ----
  var cf = $("#complaint-form");
  if (cf) {
    var id = (location.search.match(/id=(\d+)/) || [])[1];
    if (id) cf.listing_id.value = id;
    cf.onsubmit = function (ev) {
      ev.preventDefault();
      var b = {}; $$("[name]", cf).forEach(function (i) { b[i.name] = i.value; });
      api("complaint", { body: b }).then(function () { cf.hidden = true; $("#complaint-done").hidden = false; })
        .catch(function (e) { $("#complaint-msg").textContent = "提交失败：" + e.message; });
    };
  }
})();
// copy buttons: <button data-copy="text">
document.addEventListener("click", function (ev) {
  var b = ev.target.closest && ev.target.closest("[data-copy]");
  if (!b) return;
  var t = b.getAttribute("data-copy"), old = b.textContent;
  var done = function () { b.textContent = "已复制，打开支付宝即可"; setTimeout(function () { b.textContent = old; }, 2500); };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, function () { prompt("复制下面的口令：", t); });
  else prompt("复制下面的口令：", t);
});
// ---- site search: header and home boxes (.qbox + sibling .qres), index from /search.json ----
(function () {
  var idx = null, loading = null;
  function load() {
    if (idx) return Promise.resolve(idx);
    if (!loading) loading = fetch("/search.json").then(function (r) { return r.json(); }).then(function (j) {
      idx = j.map(function (x) { x.h = (x.t + " " + x.k).toLowerCase(); x.tl = x.t.toLowerCase(); return x; }); return idx;
    });
    return loading;
  }
  function find(q) {
    var toks = q.toLowerCase().replace(/区$/, "").split(/[\s,，]+/).filter(Boolean);
    if (!toks.length) return [];
    return idx.filter(function (x) { return toks.every(function (t) { return x.h.indexOf(t) >= 0; }); })
      .map(function (x) { var s = 0; toks.forEach(function (t) { if (x.tl.indexOf(t) >= 0) s += 2; }); if (x.tl.indexOf(toks[0]) === 0) s += 1; return [s, x]; })
      .sort(function (a, b) { return b[0] - a[0]; }).slice(0, 8).map(function (p) { return p[1]; });
  }
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); };
  document.querySelectorAll(".qbox").forEach(function (box) {
    var res = box.parentNode.querySelector(".qres"), sel = -1, cur = [];
    function render() {
      if (!cur.length) { res.innerHTML = box.value.trim() ? '<p class="qnone">没找到，换个说法试试，比如「Claude Pro」「土耳其」</p>' : ""; res.hidden = !box.value.trim(); return; }
      res.innerHTML = cur.map(function (x, i) {
        return '<a href="' + esc(x.u) + '" class="' + (i === sel ? "on" : "") + '"><span>' + esc(x.t) + '</span><small>' + esc(x.g) + (x.d ? " · " + esc(x.d) : "") + "</small></a>";
      }).join("");
      res.hidden = false;
    }
    box.addEventListener("focus", load);
    var sTimer = 0;
    box.addEventListener("input", function () {
      load().then(function () { cur = find(box.value); sel = -1; render(); });
      clearTimeout(sTimer);
      sTimer = setTimeout(function () { var v = box.value.trim(); if (v.length >= 2 && window.bbEv) window.bbEv.push({ t: "search", q: v, n: cur.length }); }, 1500);
    });
    box.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown") { sel = Math.min(sel + 1, cur.length - 1); render(); ev.preventDefault(); }
      else if (ev.key === "ArrowUp") { sel = Math.max(sel - 1, 0); render(); ev.preventDefault(); }
      else if (ev.key === "Enter" && cur.length) { location.href = cur[Math.max(sel, 0)].u; }
      else if (ev.key === "Escape") { res.hidden = true; }
    });
    document.addEventListener("click", function (ev) { if (!box.parentNode.contains(ev.target)) res.hidden = true; });
  });
})();
// ---- product filter (second dimension). State: ?p=a,b  >  localStorage  >  all ----
(function () {
  var bar = document.querySelector(".pfilter");
  if (!bar) return;
  var NAMES = {};
  bar.querySelectorAll("[data-pf]").forEach(function (b) { NAMES[b.dataset.pf] = b.textContent; });
  function read() {
    var q = new URLSearchParams(location.search).get("p");
    var v = q !== null ? q : (function () { try { return localStorage.getItem("bbwith-prods") || ""; } catch (e) { return ""; } })();
    return v.split(",").filter(function (x) { return NAMES[x] && x !== "all"; });
  }
  var sel = read();
  function apply() {
    var all = !sel.length;
    document.querySelectorAll("[data-prod]").forEach(function (el) {
      el.hidden = !all && el.dataset.prod.split(" ").every(function (p) { return sel.indexOf(p) < 0; });
    });
    // lists that should show only their first two matching items
    document.querySelectorAll("ul.top2").forEach(function (ul) {
      var n = 0;
      Array.prototype.forEach.call(ul.children, function (li) { if (!li.hidden) { n++; if (n > 2) li.hidden = true; } });
    });
    bar.querySelectorAll("[data-pf]").forEach(function (b) {
      b.classList.toggle("on", b.dataset.pf === "all" ? all : sel.indexOf(b.dataset.pf) >= 0);
    });
    bar.querySelector(".pf-sum").textContent = all ? "全部产品" : sel.map(function (x) { return NAMES[x]; }).join("、");
    bar.classList.toggle("active", !all);
    // deals badge follows the filter
    var bd = document.querySelector(".top nav.main .badge[data-by]");
    if (bd) {
      var by = JSON.parse(bd.dataset.by), n = 0;
      Object.keys(by).forEach(function (k) { if (all || sel.indexOf(k) >= 0) n += by[k]; });
      bd.textContent = n; bd.hidden = !n;
    }
    // say so when the filter leaves a list empty, instead of a blank page
    document.querySelectorAll(".fl").forEach(function (box) {
      var items = box.querySelectorAll("[data-prod]");
      var shown = Array.prototype.some.call(items, function (el) { return !el.hidden; });
      box.querySelectorAll("h2").forEach(function (h) {
        var nxt = h.nextElementSibling;
        if (nxt && nxt.querySelector("[data-prod]")) h.hidden = !Array.prototype.some.call(nxt.querySelectorAll("[data-prod]"), function (el) { return !el.hidden; });
      });
      var em = box.querySelector(".fl-empty");
      if (em) { em.hidden = shown || !items.length; var s2 = em.querySelector(".fl-sel"); if (s2) s2.textContent = sel.map(function (x) { return NAMES[x]; }).join("、"); }
    });
    // keep the choice when moving between tabs
    document.querySelectorAll(".top nav.main a").forEach(function (a) {
      var u = a.getAttribute("href").split("?")[0];
      a.setAttribute("href", all ? u : u + "?p=" + sel.join(","));
    });
    try { localStorage.setItem("bbwith-prods", sel.join(",")); } catch (e) {}
    var url = location.pathname + (all ? "" : "?p=" + sel.join(",")) + location.hash;
    history.replaceState(null, "", url);
  }
  bar.querySelector(".pf-toggle").addEventListener("click", function () {
    var c = bar.querySelector(".pf-chips"); c.hidden = !c.hidden;
    this.setAttribute("aria-expanded", String(!c.hidden));
  });
  document.addEventListener("click", function (ev) {
    if (ev.target.closest("[data-pf-reset]")) { sel = []; apply(); }
  });
  bar.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-pf]");
    if (!b) return;
    var k = b.dataset.pf;
    if (k === "all") sel = [];
    else if (sel.indexOf(k) >= 0) sel.splice(sel.indexOf(k), 1);
    else sel.push(k);
    apply();
  });
  apply();
})();

// data freshness: a ring that drains until the next update, colour going green -> amber as the data ages,
// with a dot orbiting once a minute so the clock visibly runs
(function () {
  var cells = document.querySelectorAll(".fr[data-t]");
  if (!cells.length) return;
  function dur(s) {
    s = Math.max(0, Math.floor(s));
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    if (d) return d + " 天 " + h + " 小时";
    if (h) return h + " 小时 " + m + " 分";
    return m ? m + " 分钟" : "不到 1 分钟";
  }
  function clock(s) {
    s = Math.max(0, Math.floor(s));
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(Math.floor(s / 3600)) + ":" + p(Math.floor(s % 3600 / 60)) + ":" + p(s % 60);
  }
  function tick() {
    var nowMs = Date.now(), now = nowMs / 1000;
    cells.forEach(function (c) {
      var t = Date.parse(c.dataset.t) / 1000, per = +c.dataset.period;
      if (isNaN(t)) return;
      var age = now - t, left = per - age, frac = Math.min(1, Math.max(0, left / per));
      var hue = Math.round(35 + 125 * frac);           // 160 = fresh green ... 35 = amber
      c.style.setProperty("--h", hue);
      c.querySelector(".arc").style.strokeDasharray = (frac * 100).toFixed(2) + " 100";
      c.querySelector(".sec").setAttribute("transform", "rotate(" + ((nowMs / 1000 % 60) * 6).toFixed(1) + " 32 32)");
      c.querySelector(".ago").textContent = dur(age) + "前更新";
      c.title = c.querySelector(".fr-n").textContent + "：" + dur(age) + "前更新";
      var cd = c.querySelector(".cd");
      var nx = c.querySelector(".fr-next");
      if (left <= -1800) {
        // overdue: just tell the reader how old the prices are; failures are the operator's business (/admin, GitHub email)
        if (nx.firstChild && nx.firstChild.nodeType === 3) nx.firstChild.textContent = "";
        cd.textContent = dur(age) + "前更新";
        c.classList.add("late"); c.classList.remove("busy");
      } else if (left > 0) { cd.textContent = clock(left); c.classList.remove("busy", "late"); }
      else { cd.textContent = "正在更新…"; c.classList.add("busy"); }
    });
    requestAnimationFrame(function () {});
  }
  tick(); setInterval(tick, 250);
})();

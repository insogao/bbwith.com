// bbwith: page views, up/down votes, merchant / complaint / admin forms. No framework, no cookies.
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

  // page views (one small request; no cookies, no IDs)
  try {
    if (!/^\/(admin|merchant\/manage)/.test(location.pathname) && navigator.sendBeacon)
      navigator.sendBeacon("/api/pv", location.pathname);
  } catch (e) {}

  // votes: <span class="vote" data-target="listing:12"></span>
  var boxes = $$(".vote[data-target]");
  function paint(box, s) {
    box.innerHTML = '<button type="button" data-v="1" class="' + (s.mine === 1 ? "on" : "") + '" title="有用">👍 <b>' + (s.up || 0) +
      '</b></button><button type="button" data-v="-1" class="' + (s.mine === -1 ? "on" : "") + '" title="不靠谱">👎 <b>' + (s.down || 0) + "</b></button>";
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

(function () {
  "use strict";
  var api = window.bbApi, esc = window.bbEsc, root = document.getElementById("admin");
  function login() {
    root.innerHTML = '<form id="login"><label>管理员密钥<input type="password" name="k" autocomplete="off"></label> <button class="btn small">进入</button></form>';
    document.getElementById("login").onsubmit = function (e) {
      e.preventDefault(); localStorage.setItem("bbwith-admin", this.k.value); load();
    };
  }
  function table(rows, cols) {
    return '<div class="tablewrap"><table class="prices"><thead><tr>' + cols.map(function (c) { return "<th>" + c[0] + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.map(function (r) { return "<tr>" + cols.map(function (c) { return "<td>" + c[1](r) + "</td>"; }).join("") + "</tr>"; }).join("") +
      "</tbody></table></div>";
  }
  function btn(kind, id, action, label) { return '<button class="btn small" data-kind="' + kind + '" data-id="' + id + '" data-action="' + action + '">' + label + "</button>"; }
  function load() {
    api("admin/overview", { admin: true }).then(function (j) {
      var link = function (l) { return '<a href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(l.title) + "</a>"; };
      root.innerHTML =
        "<h2>待审核商品（" + j.pending.length + "）</h2>" + table(j.pending, [
          ["商家", function (l) { return esc(l.merchant) + "<br><small>" + esc(l.contact) + "</small>"; }],
          ["商品", link], ["档位 / 方式", function (l) { return esc(l.plan_key) + "<br>" + esc(l.type) + " · 质保 " + l.warranty_days + " 天"; }],
          ["价格", function (l) { return "¥" + l.price; }],
          ["操作", function (l) { return btn("listing", l.id, "approve", "通过") + " " + btn("listing", l.id, "reject", "拒绝"); }]]) +
        "<h2>投诉</h2>" + table(j.complaints, [
          ["状态", function (c) { return c.status === "pending" ? "<b>待审</b>" : (c.resolved ? "已解决" : "已公开"); }],
          ["商家 / 商品", function (c) { return esc(c.merchant) + "<br><small>#" + c.listing_id + " " + esc(c.title) + "</small>"; }],
          ["问题", function (c) { return "<b>" + esc(c.problem) + "</b> " + esc(c.detail) + "<br><small>凭证：" + esc(c.order_ref) + " · 联系：" + esc(c.contact || "—") + "</small>" + (c.reply ? "<br><small>商家回复：" + esc(c.reply) + "</small>" : ""); }],
          ["操作", function (c) { return c.status === "pending" ? btn("complaint", c.id, "publish", "公开") + " " + btn("complaint", c.id, "reject", "驳回")
              : btn("complaint", c.id, c.resolved ? "unresolve" : "resolve", c.resolved ? "改为未解决" : "标记已解决"); }]]) +
        "<h2>已上架商品（" + j.listings.length + "）</h2>" + table(j.listings, [
          ["商家", function (l) { return esc(l.merchant) + (l.merchant_status !== "active" ? "（已停用）" : ""); }], ["商品", link],
          ["档位", function (l) { return esc(l.plan_key) + " · " + esc(l.type); }], ["价格", function (l) { return "¥" + l.price; }],
          ["人工核价", function (l) { return esc((l.manual_verified_at || "—").slice(0, 10)); }],
          ["操作", function (l) { return btn("listing", l.id, "verify", "人工核价通过") + " " + btn("listing", l.id, "remove", "下架") + " " +
              btn("merchant", l.merchant_id, "banned", "停用商家"); }]]) +
        "<h2>近 30 天：每日浏览和外链点击</h2>" + table(j.daily, [["日期", function (d) { return d.day; }], ["浏览", function (d) { return d.pv; }],
          ["点击", function (d) { return d.clicks; }], ["点击率", function (d) { return d.pv ? (d.clicks / d.pv * 100).toFixed(1) + "%" : "—"; }]]) +
        "<h2>外链点击（按链接）</h2>" + table(j.clicks, [["链接", function (c) { return "/go/" + esc(c.key); }], ["点击", function (c) { return c.n; }]]) +
        "<h2>外链点击（按来源页面）</h2>" + table(j.click_src, [["来源", function (c) { return esc(c.src); }], ["点击", function (c) { return c.n; }]]) +
        "<h2>页面浏览</h2>" + table(j.pv, [["页面", function (p) { return esc(p.path); }], ["浏览", function (p) { return p.n; }]]) +
        '<p><button class="btn small ghost" id="logout">退出</button></p>';
      document.getElementById("logout").onclick = function () { localStorage.removeItem("bbwith-admin"); login(); };
    }).catch(function (e) { if (/管理员/.test(e.message)) login(); else root.innerHTML = "<p>加载失败：" + esc(e.message) + "</p>"; });
  }
  root.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-kind]");
    if (!b) return;
    var body = { id: +b.dataset.id, action: b.dataset.action };
    if (b.dataset.kind === "merchant") { if (!confirm("停用后该商家所有商品都会下线，确定？")) return; body = { id: +b.dataset.id, status: "banned" }; }
    if (b.dataset.action === "reject" || b.dataset.action === "remove") body.note = prompt("原因（商家可见，可留空）") || "";
    api("admin/" + b.dataset.kind, { admin: true, body: body }).then(load).catch(function (er) { alert(er.message); });
  });
  load();
})();

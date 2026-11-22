// Click a header with data-sort to sort a .sortable table by that column.
document.querySelectorAll("table.sortable").forEach(function (table) {
  table.querySelectorAll("th").forEach(function (th, col) {
    if (!th.hasAttribute("data-sort")) return;
    var asc = true;
    th.addEventListener("click", function () {
      var body = table.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var x = parseFloat(a.cells[col].getAttribute("data-v")) || 0;
        var y = parseFloat(b.cells[col].getAttribute("data-v")) || 0;
        return asc ? x - y : y - x;
      });
      asc = !asc;
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
});

// Currency selector: amounts are rendered in USD (data-usd); window.FX holds units per USD.
(function () {
  var sel = document.querySelectorAll("select#cur");
  if (!sel.length || !window.FX) return;
  var SYM = { USD: "$", CNY: "¥", EUR: "€", GBP: "£", JPY: "JP¥", HKD: "HK$", SGD: "S$" };
  function fmt(v, c) {
    var digits = c === "JPY" || v >= 1000 ? 0 : 2;
    return (SYM[c] || c + " ") + v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function apply(c) {
    if (!window.FX[c]) c = "USD";
    document.querySelectorAll(".m").forEach(function (el) {
      el.textContent = fmt(parseFloat(el.getAttribute("data-usd")) * window.FX[c], c);
    });
    document.querySelectorAll(".mh").forEach(function (el) { el.textContent = c; });
    sel.forEach(function (s) { s.value = c; });
  }
  var saved = "USD";
  try { saved = localStorage.getItem("bbwith-cur3") || "USD"; } catch (e) {}
  apply(saved);
  sel.forEach(function (s) {
    s.addEventListener("change", function () {
      try { localStorage.setItem("bbwith-cur3", s.value); } catch (e) {}
      apply(s.value);
    });
  });
})();

// "show the rest" rows in long tables
document.addEventListener("click", function (ev) {
  var b = ev.target.closest && ev.target.closest("[data-more]");
  if (!b) return;
  var t = b.closest("table"), more = t.querySelector("tbody.more");
  more.hidden = !more.hidden;
  b.textContent = more.hidden ? b.getAttribute("data-label") : "收起 ▴";
});
document.querySelectorAll("[data-more]").forEach(function (b) { b.setAttribute("data-label", b.textContent); });

// phones: every table cell gets its column name, so CSS can lay rows out as cards
document.querySelectorAll("table.prices:not(.rank3)").forEach(function (t) {
  var heads = Array.prototype.map.call(t.querySelectorAll("thead th"), function (th) { return th.textContent.replace(/[↕▾▴]/g, "").trim(); });
  t.querySelectorAll("tbody tr").forEach(function (tr) {
    Array.prototype.forEach.call(tr.cells, function (td, i) { if (heads[i] && !td.hasAttribute("colspan") && !td.hasAttribute("data-label")) td.setAttribute("data-label", heads[i]); });
  });
});

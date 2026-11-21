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

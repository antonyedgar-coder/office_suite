(function () {
  function visibleRows(root) {
    return Array.prototype.filter.call(root.querySelectorAll(".js-tb-row"), function (row) {
      return !row.hidden && row.offsetParent !== null && row.getAttribute("data-open-url");
    });
  }

  function select(root, row) {
    if (!row) return;
    root.querySelectorAll(".js-tb-row.is-selected").forEach(function (item) {
      item.classList.remove("is-selected");
    });
    row.classList.add("is-selected");
    if (typeof row.focus === "function") row.focus({ preventScroll: false });
    if (typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ block: "nearest" });
    }
  }

  function openRow(row) {
    var url = row && row.getAttribute("data-open-url");
    if (!url) return;
    var next = window.location.pathname + window.location.search;
    var join = url.indexOf("?") >= 0 ? "&" : "?";
    window.location.href = url + join + "next=" + encodeURIComponent(next);
  }

  function typingTarget(el) {
    if (!el || !el.closest) return false;
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return true;
    if (el.isContentEditable) return true;
    return Boolean(el.closest("button, a, .filtered-select, .dropdown"));
  }

  function bind(root) {
    if (root.dataset.tbNavReady === "1") return;
    root.dataset.tbNavReady = "1";

    root.addEventListener("click", function (event) {
      if (event.target.closest(".js-tb-toggle")) return;
      var row = event.target.closest(".js-tb-row");
      if (!row || !root.contains(row)) return;
      select(root, row);
    });

    root.addEventListener("dblclick", function (event) {
      if (event.target.closest(".js-tb-toggle")) return;
      var row = event.target.closest(".js-tb-row");
      if (!row || !root.contains(row)) return;
      event.preventDefault();
      openRow(row);
    });

    document.addEventListener("keydown", function (event) {
      if (typingTarget(event.target)) return;
      var rows = visibleRows(root);
      if (!rows.length) return;
      var current = root.querySelector(".js-tb-row.is-selected");
      if (current && (current.hidden || rows.indexOf(current) < 0)) current = null;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!current) {
          select(root, rows[0]);
          return;
        }
        var next = rows[rows.indexOf(current) + (event.key === "ArrowDown" ? 1 : -1)];
        if (next) select(root, next);
        return;
      }
      if (event.key === "Enter" && current) {
        event.preventDefault();
        openRow(current);
      }
    });
  }

  document.querySelectorAll(".js-tb-nav").forEach(bind);
})();

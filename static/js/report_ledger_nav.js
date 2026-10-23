(function () {
  function visibleLedgers(root) {
    return Array.prototype.filter.call(root.querySelectorAll(".js-report-ledger"), function (el) {
      return el.offsetParent !== null && el.getAttribute("data-account-id");
    });
  }

  function rowIndex(el) {
    var row = el.closest("tr");
    if (!row || !row.parentNode) return 0;
    return Array.prototype.indexOf.call(row.parentNode.children, row);
  }

  function colOf(el) {
    return Number(el.getAttribute("data-col") || 0);
  }

  function openLedger(root, el) {
    var accountId = el && el.getAttribute("data-account-id");
    if (!accountId) return;
    var params = new URLSearchParams();
    params.set("account", accountId);
    var dateFrom = root.getAttribute("data-date-from") || "";
    var dateTo = root.getAttribute("data-date-to") || "";
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    params.set("next", window.location.pathname + window.location.search);
    var base = root.getAttribute("data-ledger-url") || "/accounts/reports/ledger/";
    window.location.href = base + (base.indexOf("?") >= 0 ? "&" : "?") + params.toString();
  }

  function select(root, el) {
    if (!el) return;
    root.querySelectorAll(".js-report-ledger.is-selected").forEach(function (item) {
      item.classList.remove("is-selected");
    });
    el.classList.add("is-selected");
    if (typeof el.focus === "function") el.focus({ preventScroll: false });
    if (typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function move(root, dx, dy) {
    var cells = visibleLedgers(root);
    if (!cells.length) return;
    var current = root.querySelector(".js-report-ledger.is-selected");
    if (!current || cells.indexOf(current) < 0) {
      select(root, cells[0]);
      return;
    }
    if (dx !== 0) {
      var wantCol = colOf(current) + dx;
      var currentRow = rowIndex(current);
      var best = null;
      var bestScore = Infinity;
      cells.forEach(function (el) {
        if (colOf(el) !== wantCol) return;
        var score = Math.abs(rowIndex(el) - currentRow);
        if (score < bestScore) {
          best = el;
          bestScore = score;
        }
      });
      if (best) select(root, best);
      return;
    }
    if (dy !== 0) {
      var sameCol = cells.filter(function (el) {
        return colOf(el) === colOf(current);
      });
      var idx = sameCol.indexOf(current);
      var next = sameCol[idx + dy];
      if (next) select(root, next);
    }
  }

  function typingTarget(el) {
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return true;
    if (el.isContentEditable) return true;
    return Boolean(
      el.closest && el.closest("button, a, .filtered-select, .dropdown, .pnl-toggle")
    );
  }

  function bind(root) {
    if (root.dataset.ledgerNavReady === "1") return;
    root.dataset.ledgerNavReady = "1";

    root.addEventListener("click", function (event) {
      var el = event.target.closest(".js-report-ledger");
      if (!el || !root.contains(el)) return;
      select(root, el);
    });

    root.addEventListener("dblclick", function (event) {
      var el = event.target.closest(".js-report-ledger");
      if (!el || !root.contains(el)) return;
      event.preventDefault();
      openLedger(root, el);
    });

    document.addEventListener("keydown", function (event) {
      if (typingTarget(event.target)) return;
      var current = root.querySelector(".js-report-ledger.is-selected");
      var cells = visibleLedgers(root);
      if (!cells.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        move(root, 0, 1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        move(root, 0, -1);
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        move(root, -1, 0);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        move(root, 1, 0);
        return;
      }
      if (event.key === "Enter" && current) {
        event.preventDefault();
        openLedger(root, current);
      }
    });
  }

  document.querySelectorAll(".js-report-ledger-nav").forEach(bind);
})();

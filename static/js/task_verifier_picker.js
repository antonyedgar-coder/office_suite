(function () {
  window.initTaskVerifierPicker = function (opts) {
    var staffUsers = opts.staffUsers || [];
    var searchEl = document.getElementById(opts.searchId || "taskVerifierSearch");
    var suggestEl = document.getElementById(opts.suggestId || "taskVerifierSuggestions");
    var chipsEl = document.getElementById(opts.chipsId || "verifierChips");
    var hiddenEl = document.getElementById(opts.hiddenId || "taskVerifierIdsHidden");
    var minChars = opts.minChars || 2;
    var selected = {};

    function renderChips() {
      if (!chipsEl) return;
      chipsEl.innerHTML = "";
      Object.keys(selected).forEach(function (id) {
        var chip = document.createElement("span");
        chip.className = "assignee-chip";
        chip.innerHTML =
          "<span>" +
          selected[id] +
          '</span><button type="button" data-remove="' +
          id +
          '" aria-label="Remove">&times;</button>';
        chipsEl.appendChild(chip);
      });
      if (hiddenEl) hiddenEl.value = Object.keys(selected).join(",");
    }

    function loadInitial(ids) {
      (ids || []).forEach(function (item) {
        selected[String(item.id)] = item.label;
      });
      renderChips();
    }

    function showSuggestions(q) {
      if (!suggestEl) return;
      suggestEl.innerHTML = "";
      var qq = (q || "").trim().toLowerCase();
      if (qq.length < minChars) {
        suggestEl.classList.remove("show");
        return;
      }
      var shown = 0;
      staffUsers.forEach(function (u) {
        if (selected[String(u.id)]) return;
        var hay = (u.search || u.label || "").toLowerCase();
        if (hay.indexOf(qq) === -1) return;
        var item = document.createElement("div");
        item.className = "task-suggest-item";
        item.textContent = u.label;
        item.addEventListener("mousedown", function (e) {
          e.preventDefault();
          selected[String(u.id)] = u.label;
          renderChips();
          if (searchEl) searchEl.value = "";
          suggestEl.classList.remove("show");
        });
        suggestEl.appendChild(item);
        shown++;
        if (shown >= 30) return;
      });
      if (shown) suggestEl.classList.add("show");
      else suggestEl.classList.remove("show");
    }

    if (chipsEl) {
      chipsEl.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-remove]");
        if (!btn) return;
        delete selected[btn.getAttribute("data-remove")];
        renderChips();
      });
    }
    if (searchEl) {
      searchEl.addEventListener("input", function () {
        showSuggestions(searchEl.value);
      });
      searchEl.addEventListener("blur", function () {
        setTimeout(function () {
          if (suggestEl) suggestEl.classList.remove("show");
        }, 150);
      });
    }

    loadInitial(opts.initial || []);
    return { renderChips: renderChips, loadInitial: loadInitial };
  };
})();

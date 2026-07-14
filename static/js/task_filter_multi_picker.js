(function () {
  /**
   * Multi-select searchable filter: type to search, click to add chips, remove chips.
   * Hidden input stores comma-separated IDs.
   */
  window.initTaskFilterMultiPicker = function (opts) {
    var options = opts.options || [];
    var searchEl = document.getElementById(opts.searchId);
    var suggestEl = document.getElementById(opts.suggestId);
    var chipsEl = document.getElementById(opts.chipsId);
    var hiddenEl = document.getElementById(opts.hiddenId);
    var minChars = opts.minChars == null ? 0 : opts.minChars;
    var selected = {};

    if (!searchEl || !suggestEl || !chipsEl || !hiddenEl) return;

    function optionById(id) {
      for (var i = 0; i < options.length; i++) {
        if (String(options[i].id) === String(id)) return options[i];
      }
      return null;
    }

    function syncHidden() {
      hiddenEl.value = Object.keys(selected).join(",");
    }

    function renderChips() {
      chipsEl.innerHTML = "";
      Object.keys(selected).forEach(function (id) {
        var o = selected[id];
        var chip = document.createElement("span");
        chip.className = "task-filter-chip";
        chip.innerHTML =
          '<span class="task-filter-chip-label"></span>' +
          '<button type="button" class="task-filter-chip-remove" aria-label="Remove" data-id="' +
          id +
          '">&times;</button>';
        chip.querySelector(".task-filter-chip-label").textContent = o.label;
        chipsEl.appendChild(chip);
      });
      syncHidden();
    }

    function addOption(o) {
      if (!o || selected[String(o.id)]) return;
      selected[String(o.id)] = o;
      renderChips();
    }

    function matchOptions(query) {
      var qq = (query || "").trim().toLowerCase();
      if (qq.length < minChars && minChars > 0) return [];
      var out = [];
      for (var i = 0; i < options.length; i++) {
        var o = options[i];
        if (selected[String(o.id)]) continue;
        var label = (o.label || "").toLowerCase();
        var search = (o.search || label).toLowerCase();
        if (!qq || label.indexOf(qq) !== -1 || search.indexOf(qq) !== -1) {
          out.push(o);
          if (out.length >= 40) break;
        }
      }
      return out;
    }

    function renderSuggestions(query) {
      suggestEl.innerHTML = "";
      var matches = matchOptions(query);
      if (!matches.length) {
        suggestEl.classList.remove("show");
        return;
      }
      matches.forEach(function (o) {
        var item = document.createElement("div");
        item.className = "task-suggest-item";
        item.textContent = o.label;
        item.addEventListener("mousedown", function (e) {
          e.preventDefault();
          addOption(o);
          searchEl.value = "";
          suggestEl.classList.remove("show");
          searchEl.focus();
        });
        suggestEl.appendChild(item);
      });
      suggestEl.classList.add("show");
    }

    // Restore from hidden value (comma-separated IDs)
    var initial = (hiddenEl.value || "").split(",");
    for (var i = 0; i < initial.length; i++) {
      var id = (initial[i] || "").trim();
      if (!id) continue;
      var found = optionById(id);
      if (found) selected[String(found.id)] = found;
    }
    renderChips();

    searchEl.addEventListener("input", function () {
      renderSuggestions(searchEl.value);
    });
    searchEl.addEventListener("focus", function () {
      renderSuggestions(searchEl.value);
    });
    searchEl.addEventListener("blur", function () {
      setTimeout(function () {
        suggestEl.classList.remove("show");
      }, 150);
    });
    chipsEl.addEventListener("click", function (e) {
      var btn = e.target.closest(".task-filter-chip-remove");
      if (!btn) return;
      var rid = btn.getAttribute("data-id");
      if (rid && selected[rid]) {
        delete selected[rid];
        renderChips();
      }
    });
  };
})();

(function () {
  /**
   * Single-select staff user search: type to filter, click suggestion to select.
   */
  window.initTaskUserSinglePicker = function (opts) {
    var options = opts.options || [];
    var searchEl = document.getElementById(opts.searchId);
    var suggestEl = document.getElementById(opts.suggestId);
    var hiddenEl = document.getElementById(opts.hiddenId);
    var minChars = opts.minChars == null ? 1 : opts.minChars;

    if (!searchEl || !suggestEl || !hiddenEl) return;

    function matchOptions(query) {
      var qq = (query || "").trim().toLowerCase();
      if (qq.length < minChars) return [];
      var out = [];
      for (var i = 0; i < options.length; i++) {
        var o = options[i];
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
          hiddenEl.value = String(o.id);
          searchEl.value = o.label;
          suggestEl.classList.remove("show");
        });
        suggestEl.appendChild(item);
      });
      suggestEl.classList.add("show");
    }

    function syncFromHidden() {
      if (!hiddenEl.value) {
        searchEl.value = "";
        return;
      }
      for (var i = 0; i < options.length; i++) {
        if (String(options[i].id) === String(hiddenEl.value)) {
          searchEl.value = options[i].label;
          break;
        }
      }
    }

    function clearIfNoMatch() {
      var v = (searchEl.value || "").trim();
      var match = null;
      for (var i = 0; i < options.length; i++) {
        if (options[i].label === v) {
          match = options[i];
          break;
        }
      }
      hiddenEl.value = match ? String(match.id) : "";
    }

    syncFromHidden();
    searchEl.addEventListener("input", function () {
      hiddenEl.value = "";
      renderSuggestions(searchEl.value);
    });
    searchEl.addEventListener("blur", function () {
      setTimeout(function () {
        clearIfNoMatch();
        suggestEl.classList.remove("show");
      }, 150);
    });
    searchEl.addEventListener("focus", function () {
      renderSuggestions(searchEl.value);
    });
  };
})();

(function () {
  function optionLabel(option) {
    return (option.text || "").replace(/\s+/g, " ").trim();
  }

  function enhance(select) {
    if (select.dataset.filteredReady === "1") return;
    select.dataset.filteredReady = "1";

    var wrap = document.createElement("div");
    wrap.className = "filtered-select";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("filtered-select-source");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    var inputId = select.id || "";
    if (inputId) {
      select.id = inputId + "_source";
    }

    var input = document.createElement("input");
    input.type = "text";
    input.className = "form-select filtered-select-input";
    input.setAttribute("autocomplete", "off");
    input.setAttribute("spellcheck", "false");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    if (inputId) input.id = inputId;
    input.setAttribute("placeholder", select.getAttribute("data-placeholder") || "Type to search");

    var listId = (inputId || "filtered-select") + "_list";
    var list = document.createElement("div");
    list.className = "filtered-select-menu";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    input.setAttribute("aria-controls", listId);

    wrap.appendChild(input);
    wrap.appendChild(list);

    var visible = [];
    var activeIndex = -1;

    function selectedOption() {
      if (select.selectedIndex < 0) return null;
      return select.options[select.selectedIndex] || null;
    }

    function syncInputFromSelect() {
      var option = selectedOption();
      input.value = option ? optionLabel(option) : "";
    }

    function setActive(index) {
      if (!visible.length) {
        activeIndex = -1;
        input.removeAttribute("aria-activedescendant");
        return;
      }
      if (index < 0) index = visible.length - 1;
      if (index >= visible.length) index = 0;
      activeIndex = index;
      visible.forEach(function (item, i) {
        item.classList.toggle("is-active", i === activeIndex);
        item.setAttribute("aria-selected", i === activeIndex ? "true" : "false");
      });
      var active = visible[activeIndex];
      if (active) {
        input.setAttribute("aria-activedescendant", active.id);
        if (typeof active.scrollIntoView === "function") {
          active.scrollIntoView({ block: "nearest" });
        }
      }
    }

    function choose(option) {
      if (!option) return;
      select.value = option.value;
      syncInputFromSelect();
      close();
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function close() {
      list.hidden = true;
      list.innerHTML = "";
      visible = [];
      activeIndex = -1;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      wrap.classList.remove("is-open");
    }

    function render(query) {
      var q = (query || "").trim().toLowerCase();
      list.innerHTML = "";
      visible = [];
      var selectedValue = select.value;
      var matchIndex = -1;
      Array.prototype.forEach.call(select.options, function (option, i) {
        var label = optionLabel(option);
        if (q && label.toLowerCase().indexOf(q) === -1) return;
        var item = document.createElement("div");
        item.className = "filtered-select-option";
        item.id = listId + "_opt_" + i;
        item.setAttribute("role", "option");
        item.setAttribute("data-value", option.value);
        item.textContent = label || "---------";
        item.addEventListener("mousedown", function (event) {
          event.preventDefault();
          choose(option);
        });
        list.appendChild(item);
        if (option.value === selectedValue) matchIndex = visible.length;
        visible.push(item);
      });
      if (!visible.length) {
        var empty = document.createElement("div");
        empty.className = "filtered-select-empty";
        empty.textContent = "No matching accounts";
        list.appendChild(empty);
        activeIndex = -1;
        input.removeAttribute("aria-activedescendant");
        return;
      }
      setActive(matchIndex >= 0 ? matchIndex : 0);
    }

    function open(query) {
      render(query);
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      wrap.classList.add("is-open");
    }

    function isOpen() {
      return !list.hidden;
    }

    input.addEventListener("focus", function () {
      open("");
      input.select();
    });
    input.addEventListener("click", function () {
      if (!isOpen()) open("");
      input.select();
    });
    input.addEventListener("input", function () {
      open(input.value);
    });
    input.addEventListener("blur", function () {
      setTimeout(function () {
        if (wrap.contains(document.activeElement)) return;
        var typed = (input.value || "").trim().toLowerCase();
        if (!typed) {
          select.value = "";
          syncInputFromSelect();
          close();
          return;
        }
        var exact = null;
        Array.prototype.forEach.call(select.options, function (option) {
          if (exact) return;
          if (optionLabel(option).toLowerCase() === typed) exact = option;
        });
        if (exact) choose(exact);
        else syncInputFromSelect();
        close();
      }, 120);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (!isOpen()) open(input.value);
        else setActive(activeIndex + 1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (!isOpen()) open(input.value);
        else setActive(activeIndex - 1);
        return;
      }
      if (event.key === "Home" && isOpen()) {
        event.preventDefault();
        setActive(0);
        return;
      }
      if (event.key === "End" && isOpen()) {
        event.preventDefault();
        setActive(visible.length - 1);
        return;
      }
      if (event.key === "Enter" && isOpen()) {
        event.preventDefault();
        if (activeIndex >= 0 && visible[activeIndex]) {
          var value = visible[activeIndex].getAttribute("data-value");
          var option = Array.prototype.find.call(select.options, function (row) {
            return row.value === value;
          });
          choose(option);
        }
        return;
      }
      if (event.key === "Escape") {
        if (isOpen()) {
          event.preventDefault();
          syncInputFromSelect();
          close();
        }
      }
    });

    document.addEventListener("mousedown", function (event) {
      if (!wrap.contains(event.target)) close();
    });

    syncInputFromSelect();
  }

  document.querySelectorAll("select.js-filtered-select").forEach(enhance);
})();

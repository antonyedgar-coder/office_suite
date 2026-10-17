(function () {
  function sortSelect(select) {
    var options = Array.prototype.slice.call(select.options);
    options.sort(function (a, b) {
      return a.text.localeCompare(b.text);
    });
    options.forEach(function (option) {
      select.appendChild(option);
    });
  }

  function moveSelected(from, to) {
    Array.prototype.slice.call(from.selectedOptions).forEach(function (option) {
      option.selected = false;
      to.appendChild(option);
    });
    sortSelect(to);
  }

  function enhance(source) {
    if (source.dataset.dualListReady === "1") return;
    source.dataset.dualListReady = "1";

    var wrap = document.createElement("div");
    wrap.className = "dual-list";

    var availableCol = document.createElement("div");
    availableCol.className = "dual-list-col";
    var availableCaption = document.createElement("div");
    availableCaption.className = "dual-list-caption";
    availableCaption.textContent = source.getAttribute("data-available-label") || "Available activities";
    var available = document.createElement("select");
    available.multiple = true;
    available.className = "form-select dual-list-box";
    available.size = source.size || 14;
    available.setAttribute("aria-label", availableCaption.textContent);

    var actions = document.createElement("div");
    actions.className = "dual-list-actions";
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", "Move permissions");

    var toRight = document.createElement("button");
    toRight.type = "button";
    toRight.className = "dual-list-btn";
    toRight.dataset.move = "in";
    toRight.title = "Allow selected";
    toRight.setAttribute("aria-label", "Move selected to allowed");
    toRight.innerHTML = '<i class="bi bi-arrow-right" aria-hidden="true"></i>';

    var toLeft = document.createElement("button");
    toLeft.type = "button";
    toLeft.className = "dual-list-btn";
    toLeft.dataset.move = "out";
    toLeft.title = "Remove selected";
    toLeft.setAttribute("aria-label", "Move selected to available");
    toLeft.innerHTML = '<i class="bi bi-arrow-left" aria-hidden="true"></i>';

    var assignedCol = document.createElement("div");
    assignedCol.className = "dual-list-col";
    var assignedCaption = document.createElement("div");
    assignedCaption.className = "dual-list-caption";
    assignedCaption.textContent = source.getAttribute("data-assigned-label") || "Allowed";

    source.classList.add("dual-list-box");
    source.setAttribute("aria-label", assignedCaption.textContent);

    Array.prototype.slice.call(source.options).forEach(function (option) {
      if (!option.selected) available.appendChild(option);
    });
    Array.prototype.slice.call(source.options).forEach(function (option) {
      option.selected = false;
    });

    availableCol.appendChild(availableCaption);
    availableCol.appendChild(available);
    actions.appendChild(toRight);
    actions.appendChild(toLeft);
    assignedCol.appendChild(assignedCaption);

    source.parentNode.insertBefore(wrap, source);
    wrap.appendChild(availableCol);
    wrap.appendChild(actions);
    wrap.appendChild(assignedCol);
    assignedCol.appendChild(source);

    function allowSelected() {
      moveSelected(available, source);
    }
    function removeSelected() {
      moveSelected(source, available);
    }
    toRight.onclick = allowSelected;
    toLeft.onclick = removeSelected;
    available.ondblclick = allowSelected;
    source.ondblclick = removeSelected;

    var form = source.closest("form");
    if (form) {
      form.addEventListener("submit", function () {
        Array.prototype.slice.call(source.options).forEach(function (option) {
          option.selected = true;
        });
      });
    }
  }

  document.querySelectorAll("select.js-dual-list").forEach(enhance);
})();

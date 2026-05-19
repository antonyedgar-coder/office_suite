(function () {
  var STORAGE_COLLAPSED = "caSuite.sidebarCollapsed";
  var STORAGE_NAV_SECTIONS = "caSuite.navSections";

  function showToast(message, tag) {
    var container = document.getElementById("app-toast-container");
    if (!container || !message) return;

    var map = {
      error: { bg: "danger", icon: "exclamation-octagon" },
      success: { bg: "success", icon: "check-circle" },
      warning: { bg: "warning", icon: "exclamation-triangle" },
      info: { bg: "info", icon: "info-circle" },
    };
    var cfg = map[tag] || map.info;

    var el = document.createElement("div");
    el.className = "toast align-items-center text-bg-" + cfg.bg + " border-0 show";
    el.setAttribute("role", "alert");
    el.setAttribute("aria-live", "assertive");
    el.setAttribute("aria-atomic", "true");
    el.innerHTML =
      '<div class="d-flex">' +
      '<div class="toast-body"><i class="bi bi-' +
      cfg.icon +
      ' me-2"></i>' +
      escapeHtml(message) +
      "</div>" +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
      "</div>";

    container.appendChild(el);
    var toast = bootstrap.Toast.getOrCreateInstance(el, { delay: tag === "error" ? 8000 : 4500 });
    toast.show();
    el.addEventListener("hidden.bs.toast", function () {
      el.remove();
    });
  }

  function escapeHtml(text) {
    var d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
  }

  function initDjangoMessageToasts() {
    var holder = document.getElementById("app-django-messages");
    if (!holder) return;
    holder.querySelectorAll("[data-toast-body]").forEach(function (node) {
      var tag = node.getAttribute("data-toast-tag") || "info";
      if (tag === "debug") return;
      showToast(node.getAttribute("data-toast-body") || "", tag === "error" ? "error" : tag);
    });
    holder.remove();
  }

  function readNavSections() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_NAV_SECTIONS) || "{}");
    } catch (e) {
      return {};
    }
  }

  function writeNavSections(saved) {
    try {
      localStorage.setItem(STORAGE_NAV_SECTIONS, JSON.stringify(saved));
    } catch (e) {
      /* ignore quota errors */
    }
  }

  function setAccordionOpen(item, open) {
    var btn = item.querySelector(".nav-accordion-toggle");
    var panel = item.querySelector(".nav-accordion-panel");
    if (!btn || !panel) return;
    if (open) {
      item.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      panel.hidden = false;
    } else {
      item.classList.remove("is-open");
      btn.setAttribute("aria-expanded", "false");
      panel.hidden = true;
    }
  }

  function allAccordionItems(root) {
    return root.querySelectorAll(".nav-accordion-item[data-nav-section]");
  }

  function closeAllAccordionItems(root, exceptItem) {
    allAccordionItems(root).forEach(function (item) {
      if (item !== exceptItem) {
        setAccordionOpen(item, false);
      }
    });
  }

  function bindSidebarAccordion(root) {
    if (!root) return;
    var saved = readNavSections();
    var items = allAccordionItems(root);
    var serverOpenItems = [];

    items.forEach(function (item) {
      if (item.classList.contains("is-open")) {
        serverOpenItems.push(item);
      }
    });

    closeAllAccordionItems(root, null);

    if (serverOpenItems.length) {
      var first = serverOpenItems[0];
      setAccordionOpen(first, true);
      saved = {};
      var section = first.getAttribute("data-nav-section");
      if (section) saved[section] = true;
    }

    root.querySelectorAll(".nav-accordion-toggle").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var item = btn.closest(".nav-accordion-item");
        var panel = item && item.querySelector(".nav-accordion-panel");
        if (!item || !panel) return;
        var open = item.classList.contains("is-open");
        if (open) {
          setAccordionOpen(item, false);
          saved = {};
        } else {
          closeAllAccordionItems(root, item);
          setAccordionOpen(item, true);
          saved = {};
          var section = item.getAttribute("data-nav-section");
          if (section) saved[section] = true;
        }
        writeNavSections(saved);
      });
    });

    writeNavSections(saved);
  }

  function initSidebarCollapse() {
    var shell = document.getElementById("app-shell");
    var toggle = document.getElementById("sidebarCollapseToggle");
    if (!shell || !toggle) return;

    function apply(collapsed) {
      shell.classList.toggle("sidebar-collapsed", collapsed);
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      toggle.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
    }

    var collapsed = localStorage.getItem(STORAGE_COLLAPSED) === "1";
    apply(collapsed);

    toggle.addEventListener("click", function () {
      collapsed = !shell.classList.contains("sidebar-collapsed");
      apply(collapsed);
      localStorage.setItem(STORAGE_COLLAPSED, collapsed ? "1" : "0");
    });
  }

  function initAppShell() {
    initDjangoMessageToasts();
    initSidebarCollapse();
    document.querySelectorAll("[data-sidebar-accordion]").forEach(bindSidebarAccordion);
  }

  document.addEventListener("DOMContentLoaded", initAppShell);

  window.AppUi = { showToast: showToast };
})();

(function () {
  "use strict";

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function postMarkRead(readUrl, notifFilter) {
    var body = new URLSearchParams();
    body.set("csrfmiddlewaretoken", getCookie("csrftoken"));
    body.set("stay", "1");
    if (notifFilter) {
      body.set("notif_filter", notifFilter);
    }
    return fetch(readUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
      credentials: "same-origin",
    }).then(function (res) {
      if (!res.ok) {
        throw new Error("mark read failed");
      }
      return res.json();
    });
  }

  function updateUrlRequestId(requestId, notifFilter) {
    var url = new URL(window.location.href);
    if (requestId) {
      url.searchParams.set("request", String(requestId));
    } else {
      url.searchParams.delete("request");
    }
    if (notifFilter) {
      url.searchParams.set("notif_filter", notifFilter);
    }
    window.history.replaceState({}, "", url.toString());
  }

  function initInbox(root) {
    var notifFilter = root.getAttribute("data-notif-filter") || "all";
    var items = root.querySelectorAll(".master-request-inbox-item");
    var rows = root.querySelectorAll(".master-request-panel-row");

    function clearSelection() {
      items.forEach(function (el) {
        el.classList.remove("is-selected");
      });
      rows.forEach(function (el) {
        el.classList.remove("table-active");
      });
    }

    function selectRequest(requestId, notificationEl) {
      if (!requestId) {
        return;
      }
      clearSelection();
      if (notificationEl) {
        notificationEl.classList.add("is-selected");
      }
      var row = root.querySelector('.master-request-panel-row[data-request-id="' + requestId + '"]');
      if (row) {
        row.classList.add("table-active");
        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      updateUrlRequestId(requestId, notifFilter);
    }

    function markNotificationRead(notificationEl) {
      var readUrl = notificationEl.getAttribute("data-read-url");
      if (!readUrl || notificationEl.getAttribute("data-unread") !== "1") {
        return Promise.resolve();
      }
      return postMarkRead(readUrl, notifFilter).then(function () {
        notificationEl.setAttribute("data-unread", "0");
        notificationEl.classList.remove("list-group-item-warning");
        root.querySelectorAll(
          '.master-request-inbox-item[data-request-id="' +
            notificationEl.getAttribute("data-request-id") +
            '"]'
        ).forEach(function (el) {
          el.setAttribute("data-unread", "0");
          var li = el.closest("li");
          if (li) {
            li.classList.remove("list-group-item-warning");
          }
        });
        if (notifFilter === "unread") {
          var row = notificationEl.closest("li");
          if (row) {
            row.remove();
          }
        }
        var remaining = root.querySelectorAll(
          '.master-request-inbox-item[data-unread="1"]'
        ).length;
        document.querySelectorAll("[data-master-request-unread-badge]").forEach(function (badge) {
          if (remaining <= 0) {
            badge.remove();
          } else {
            badge.setAttribute("data-count", String(remaining));
            badge.textContent = String(remaining);
          }
        });
      });
    }

    items.forEach(function (item) {
      item.addEventListener("click", function (ev) {
        if (ev.target.closest("a, button[type='submit']")) {
          return;
        }
        var requestId = item.getAttribute("data-request-id");
        selectRequest(requestId, item);
        markNotificationRead(item).catch(function () {
          /* ignore — selection still works */
        });
      });
    });

    rows.forEach(function (row) {
      row.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) {
          return;
        }
        var requestId = row.getAttribute("data-request-id");
        var matching = root.querySelector(
          '.master-request-inbox-item[data-request-id="' + requestId + '"]'
        );
        selectRequest(requestId, matching);
        if (matching) {
          markNotificationRead(matching).catch(function () {});
        }
      });
    });

    var initial = root.getAttribute("data-selected-request");
    if (initial) {
      var initialItem = root.querySelector(
        '.master-request-inbox-item[data-request-id="' + initial + '"]'
      );
      selectRequest(initial, initialItem);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var root = document.getElementById("masterRequestInbox");
    if (root) {
      initInbox(root);
    }
  });
})();

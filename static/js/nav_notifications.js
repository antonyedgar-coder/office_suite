(function () {
  var body = document.body;
  var url = body && body.getAttribute("data-nav-counts-url");
  if (!url) {
    return;
  }

  var POLL_MS = 45000;

  function updateBadge(key, count) {
    var n = parseInt(count, 10) || 0;
    document.querySelectorAll('[data-nav-badge="' + key + '"]').forEach(function (el) {
      if (n > 0) {
        el.textContent = String(n);
        el.hidden = false;
      } else {
        el.textContent = "";
        el.hidden = true;
      }
    });
  }

  function applyCounts(data) {
    if (!data) {
      return;
    }
    var keys = [
      "master_requests",
      "dsc_notifications",
      "task_notifications",
      "task_my",
      "task_verify",
      "task_document_check",
    ];
    keys.forEach(function (key) {
      updateBadge(key, data[key] || 0);
    });
  }

  function poll() {
    fetch(url, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("nav counts failed");
        }
        return response.json();
      })
      .then(applyCounts)
      .catch(function () {
        /* ignore transient network errors */
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", poll);
  } else {
    poll();
  }
  setInterval(poll, POLL_MS);
})();

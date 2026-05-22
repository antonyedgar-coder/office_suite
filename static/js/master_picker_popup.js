(function (global) {
  var SOURCE = "caOfficePicker";

  function getModal() {
    return document.getElementById("masterPickerModal");
  }

  function getFrame() {
    return document.getElementById("masterPickerFrame");
  }

  function getLoading() {
    return document.getElementById("masterPickerLoading");
  }

  function setLoading(visible) {
    var loading = getLoading();
    if (!loading) return;
    loading.classList.toggle("d-none", !visible);
  }

  function closeMasterPicker() {
    var modal = getModal();
    var frame = getFrame();
    setLoading(false);
    if (frame) frame.src = "about:blank";
    if (modal && global.bootstrap) {
      var inst = bootstrap.Modal.getInstance(modal);
      if (inst) inst.hide();
    }
  }

  function buildEmbedUrl(url) {
    if (!url) return "";
    var sep = url.indexOf("?") >= 0 ? "&" : "?";
    return url + sep + "embed=popup";
  }

  function openMasterPicker(url, opts) {
    var modal = getModal();
    var frame = getFrame();
    if (!modal || !frame || !url) return;

    var fullUrl = buildEmbedUrl(url);
    var titleEl = document.getElementById("masterPickerModalLabel");
    if (titleEl && opts && opts.title) titleEl.textContent = opts.title;

    setLoading(true);
    frame.src = "about:blank";

    function loadFrame() {
      frame.onload = function () {
        setLoading(false);
        frame.onload = null;
      };
      frame.src = fullUrl;
    }

    if (modal.classList.contains("show")) {
      loadFrame();
      return;
    }

    modal.addEventListener(
      "shown.bs.modal",
      function onShown() {
        modal.removeEventListener("shown.bs.modal", onShown);
        loadFrame();
      },
      { once: true }
    );

    if (global.bootstrap) bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function initPickerBridge(handlers) {
    handlers = handlers || {};
    window.addEventListener("message", function (ev) {
      var d = ev.data;
      if (!d || d.source !== SOURCE) return;
      if (d.event === "close") {
        closeMasterPicker();
        return;
      }
      if (d.event === "created") {
        var fn = handlers[d.kind];
        if (typeof fn === "function") fn(d);
        closeMasterPicker();
      }
    });

    var modal = getModal();
    if (modal) {
      modal.addEventListener("hidden.bs.modal", function () {
        var frame = getFrame();
        setLoading(false);
        if (frame) frame.src = "about:blank";
      });
    }
  }

  function wirePickerButtons() {
    document.querySelectorAll("[data-master-picker-url]").forEach(function (btn) {
      if (btn.getAttribute("data-picker-wired") === "1") return;
      btn.setAttribute("data-picker-wired", "1");
      btn.addEventListener("click", function () {
        openMasterPicker(btn.getAttribute("data-master-picker-url"), {
          title: btn.getAttribute("data-master-picker-title") || "Add master",
        });
      });
    });
  }

  global.CaMasterPicker = {
    SOURCE: SOURCE,
    open: openMasterPicker,
    close: closeMasterPicker,
    init: initPickerBridge,
    wireButtons: wirePickerButtons,
  };
})(window);

(function () {
  var PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
  var CIN_RE = /^[A-Z0-9]{21}$/;
  var LLPIN_RE = /^[A-Z]{3}-[0-9]{4}$/;

  function $(id) {
    return document.getElementById(id);
  }

  function val(id) {
    var el = $(id);
    return el ? (el.value || "").trim().toUpperCase() : "";
  }

  function clientType() {
    return val("id_client_type");
  }

  function panRequired() {
    var t = clientType();
    return t && t !== "None" && t !== "Foreign Citizen";
  }

  function setFieldState(el, state, message) {
    if (!el) return;
    var wrap = el.closest("[data-validate-field]") || el.parentElement;
    var fb = wrap && wrap.querySelector(".field-feedback");
    el.classList.remove("is-valid-client", "is-invalid-client");
    if (state === "valid") {
      el.classList.add("is-valid-client");
      if (fb) {
        fb.className = "field-feedback valid";
        fb.textContent = message || "";
      }
    } else if (state === "invalid") {
      el.classList.add("is-invalid-client");
      if (fb) {
        fb.className = "field-feedback invalid";
        fb.textContent = message || "Invalid value";
      }
    } else if (fb) {
      fb.className = "field-feedback";
      fb.textContent = "";
    }
  }

  function validatePan() {
    var el = $("id_pan");
    if (!el) return true;
    var v = val("id_pan");
    if (!v) {
      if (panRequired()) {
        setFieldState(el, "invalid", "PAN is required for this client type.");
        return false;
      }
      setFieldState(el, null);
      return true;
    }
    if (!PAN_RE.test(v)) {
      setFieldState(el, "invalid", "PAN must be 10 characters: AAAAA9999A.");
      return false;
    }
    setFieldState(el, "valid", "PAN format looks good.");
    return true;
  }

  function validateGstin() {
    var el = $("id_gstin");
    if (!el) return true;
    var g = val("id_gstin");
    if (!g) {
      setFieldState(el, null);
      return true;
    }
    if (g.length !== 15) {
      setFieldState(el, "invalid", "GSTIN must be 15 characters.");
      return false;
    }
    var pan = val("id_pan");
    if (pan && g.substring(2, 12) !== pan) {
      setFieldState(el, "invalid", "Characters 3–12 of GSTIN must match PAN.");
      return false;
    }
    setFieldState(el, "valid", "GSTIN format looks good.");
    return true;
  }

  function validateCin() {
    var el = $("id_cin");
    if (!el) return true;
    var v = val("id_cin");
    if (!v) {
      setFieldState(el, null);
      return true;
    }
    if (!CIN_RE.test(v)) {
      setFieldState(el, "invalid", "CIN must be 21 letters or digits.");
      return false;
    }
    setFieldState(el, "valid");
    return true;
  }

  function validateLlpin() {
    var el = $("id_llpin");
    if (!el) return true;
    var v = val("id_llpin");
    if (!v) {
      setFieldState(el, null);
      return true;
    }
    if (!LLPIN_RE.test(v)) {
      setFieldState(el, "invalid", "LLPIN format: AAA-9999.");
      return false;
    }
    setFieldState(el, "valid");
    return true;
  }

  function wire() {
    var typeEl = $("id_client_type");
    if (typeEl) {
      typeEl.addEventListener("change", function () {
        validatePan();
        validateGstin();
      });
    }
    [["id_pan", validatePan], ["id_gstin", validateGstin], ["id_cin", validateCin], ["id_llpin", validateLlpin]].forEach(
      function (pair) {
        var el = $(pair[0]);
        if (el) el.addEventListener("blur", pair[1]);
      }
    );
  }

  document.addEventListener("DOMContentLoaded", wire);
})();

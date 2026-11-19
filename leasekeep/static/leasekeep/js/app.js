// Leasekeep progressive enhancements. Everything works without JavaScript;
// this adds chart tooltips, the mobile menu and confirmation prompts.
(function () {
  "use strict";

  // Chart tooltips: any element with data-tip="Title|value name|value name".
  var tip = null;
  function ensureTip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "tooltip";
      tip.setAttribute("role", "status");
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }
  function show(target, x, y) {
    var parts = (target.getAttribute("data-tip") || "").split("|");
    var keys = (target.getAttribute("data-tip-keys") || "").split("|");
    var el = ensureTip();
    el.textContent = "";
    var title = document.createElement("div");
    title.className = "tooltip__title";
    title.textContent = parts[0] || "";
    el.appendChild(title);
    parts.slice(1).forEach(function (line, i) {
      var row = document.createElement("div");
      row.className = "tooltip__row";
      if (keys[i]) {
        var key = document.createElement("span");
        key.className = "tooltip__key";
        key.style.background = keys[i];
        row.appendChild(key);
      }
      var space = line.indexOf(" ");
      var value = document.createElement("strong");
      value.textContent = space > 0 ? line.slice(0, space) : line;
      row.appendChild(value);
      if (space > 0) {
        var label = document.createElement("span");
        label.textContent = line.slice(space + 1);
        row.appendChild(label);
      }
      el.appendChild(row);
    });
    el.hidden = false;
    var w = el.offsetWidth, h = el.offsetHeight;
    var left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14));
    var top = y - h - 12 < 8 ? y + 16 : y - h - 12;
    el.style.left = left + "px";
    el.style.top = top + "px";
  }
  function hide() { if (tip) tip.hidden = true; }

  document.addEventListener("pointermove", function (e) {
    var t = e.target.closest && e.target.closest("[data-tip]");
    if (t) show(t, e.clientX, e.clientY); else hide();
  });
  document.addEventListener("focusin", function (e) {
    var t = e.target.closest && e.target.closest("[data-tip]");
    if (t) {
      var r = t.getBoundingClientRect();
      show(t, r.left + r.width / 2, r.top);
    }
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hide(); });

  // Mobile navigation.
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-nav-toggle]");
    if (toggle) {
      var shell = document.querySelector(".shell");
      var open = shell.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
  });

  // Confirmation for consequential actions: <button data-confirm="Are you sure?">.
  document.addEventListener("submit", function (e) {
    var btn = e.submitter || e.target.querySelector("[data-confirm]");
    var msg = btn && btn.getAttribute && btn.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });
})();

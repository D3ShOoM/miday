/*
 * Miday — small progressive enhancements. Every form also works
 * without this file (plain POST and redirect).
 */
(function () {
  "use strict";

  // --- Day / night switch -------------------------------------------------
  // The button's visible label ("Night" or "Day") follows the theme in CSS.
  var root = document.documentElement;
  var themeButton = document.getElementById("theme-toggle");
  function syncTheme() {
    var night = root.getAttribute("data-bs-theme") === "dark";
    themeButton.setAttribute("aria-label", night ? "Switch to day mode" : "Switch to night mode");
  }
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("miday-theme", next); } catch (e) { /* ignore */ }
      syncTheme();
    });
    syncTheme();
  }

  // Briefly show a message on a button ("Copied!"), then restore its icon and label.
  var CHECK = '<i class="px-g px-g-check" aria-hidden="true"></i>';
  var flashing = new WeakMap();
  function flashButton(button, html, ms) {
    var state = flashing.get(button);
    if (state) { clearTimeout(state.timer); } else { state = { idle: button.innerHTML }; flashing.set(button, state); }
    button.innerHTML = html;
    state.timer = setTimeout(function () {
      button.innerHTML = state.idle;
      flashing.delete(button);
    }, ms);
  }

  // --- Copy to clipboard ---------------------------------------------------
  // The LAN address is plain http, where navigator.clipboard doesn't exist,
  // so fall back to selecting text and execCommand("copy").
  function copyText(text, input) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return legacyCopy(text, input); });
    }
    return Promise.resolve(legacyCopy(text, input));
  }
  function legacyCopy(text, input) {
    var previous = document.activeElement;
    var field = input;
    if (!field) {
      field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
    }
    field.focus();
    field.select();
    field.setSelectionRange(0, text.length);
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    if (!input) { field.remove(); }
    // Give keyboard focus back to the button, unless the text is left selected to copy by hand.
    if ((ok || !input) && previous && previous.focus) { previous.focus({ preventScroll: true }); }
    return ok;
  }
  var COPY_KEYS = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘C" : "Ctrl+C";
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-copy], [data-copy-text]");
    if (!button) { return; }
    var input = button.dataset.copy ? document.querySelector(button.dataset.copy) : null;
    var text = input ? input.value : button.dataset.copyText;
    copyText(text, input).then(function (ok) {
      flashButton(button, ok ? CHECK + "Copied!" : "Press " + COPY_KEYS, 1800);
      if (!ok && input) { input.select(); }
    });
  });

  // --- Filter boxes --------------------------------------------------------
  document.querySelectorAll("[data-filter]").forEach(function (box) {
    var target = document.querySelector(box.dataset.filter);
    var empty = document.querySelector('[data-filter-empty="' + box.dataset.filter + '"]');
    if (!target) { return; }
    box.addEventListener("input", function () {
      var words = box.value.toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      target.querySelectorAll("[data-filter-text]").forEach(function (item) {
        var text = item.dataset.filterText.toLowerCase();
        var match = words.every(function (w) { return text.indexOf(w) !== -1; });
        item.classList.toggle("d-none", !match);
        if (match) { shown += 1; }
      });
      if (empty) { empty.classList.toggle("d-none", shown > 0); }
    });
  });

  // --- Small helpers -------------------------------------------------------
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });

  // Pasting a link into the empty "Add" form fetches its details right away.
  var autofetch = document.querySelector("[data-autofetch]");
  if (autofetch) {
    autofetch.addEventListener("paste", function () {
      setTimeout(function () {
        var button = autofetch.form.querySelector("[data-fetch-button]");
        if (/https?:\/\//i.test(autofetch.value) && button) {
          button.disabled = false;
          autofetch.form.requestSubmit(button);
        }
      }, 0);
    });
  }
  document.querySelectorAll("[data-fetch-button]").forEach(function (button) {
    button.form.addEventListener("submit", function (e) {
      if (e.submitter === button) {
        button.textContent = "Fetching…";
        button.setAttribute("aria-busy", "true");
      }
    });
  });

  function syncCheckedCount() {
    document.querySelectorAll("[data-checked-count]").forEach(function (el) {
      var n = document.querySelectorAll(el.dataset.checkedCount + " input[type=checkbox]:checked").length;
      el.textContent = n ? "(" + n + " selected)" : "";
    });
  }
  document.addEventListener("click", function (e) {
    var all = e.target.closest("[data-check-all]");
    var none = e.target.closest("[data-check-none]");
    var button = all || none;
    if (!button) { return; }
    var scope = document.querySelector(button.dataset.checkAll || button.dataset.checkNone);
    scope.querySelectorAll("[data-filter-text]:not(.d-none) input[type=checkbox]").forEach(function (box) {
      box.checked = Boolean(all);
    });
    syncCheckedCount();
  });
  document.addEventListener("change", function (e) {
    if (e.target.matches("input[type=checkbox]")) { syncCheckedCount(); }
  });
  syncCheckedCount();

  // --- Voting page: live results ---------------------------------------
  var poll = document.getElementById("poll");
  if (!poll) { return; }
  var pollUrl = poll.dataset.pollUrl;
  var OPEN_INTERVAL = Number(poll.dataset.refreshMs) || 4000;
  var CLOSED_INTERVAL = 30000;
  var timer = null;
  var countdownTimer = null;
  var failures = 0;
  var inFlight = false;

  function isClosed() {
    var status = document.getElementById("poll-status");
    return status && status.dataset.closed === "1";
  }

  // Swap every [data-live] region for its counterpart in a freshly rendered
  // page. Text boxes live outside those regions, so typing is never lost.
  // Returns the parsed page and the option cards that are new on it.
  function applyPage(html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var next = doc.getElementById("poll");
    if (!next) { window.location.reload(); return null; }
    var focusedId = document.activeElement && document.activeElement.id;
    document.querySelectorAll("[data-live][id]").forEach(function (el) {
      var fresh = doc.getElementById(el.id);
      if (!fresh) { return; }
      if (el.hasAttribute("aria-live")) {
        // Keep live regions in place so screen readers announce the new message.
        el.replaceChildren.apply(el, Array.prototype.slice.call(fresh.childNodes));
      } else {
        el.replaceWith(fresh);
      }
    });
    // Restaurants someone added to the vote since this page was loaded.
    var added = [];
    var grid = document.getElementById("options");
    var nextGrid = doc.getElementById("options");
    if (grid && nextGrid) {
      Array.prototype.slice.call(nextGrid.children).forEach(function (col) {
        if (col.id && !document.getElementById(col.id)) {
          grid.appendChild(col);
          added.push(col);
        }
      });
    }
    poll.dataset.state = next.dataset.state;
    if (focusedId) {
      var again = document.getElementById(focusedId);
      if (again && again !== document.activeElement) { again.focus({ preventScroll: true }); }
    }
    syncClosed();
    startCountdown();
    return { doc: doc, added: added };
  }

  // Comment boxes and the "add a restaurant" panel sit outside the live
  // regions, so follow the open/closed state by hand.
  function syncClosed() {
    var closed = isClosed();
    poll.querySelectorAll(".comment-form textarea, .comment-form button").forEach(function (el) {
      el.disabled = closed;
    });
    var suggest = document.getElementById("suggest");
    if (suggest) { suggest.hidden = closed; }
  }

  function schedule(delay) {
    clearTimeout(timer);
    if (document.hidden) { return; }
    var base = isClosed() ? CLOSED_INTERVAL : OPEN_INTERVAL;
    timer = setTimeout(refresh, delay !== undefined ? delay : Math.min(base * Math.pow(2, failures), 60000));
  }

  function refresh() {
    if (inFlight) { return schedule(); }
    inFlight = true;
    fetch(pollUrl + "?s=" + encodeURIComponent(poll.dataset.state), {
      headers: { "X-Requested-With": "fetch" },
      cache: "no-store",
      credentials: "same-origin",
    }).then(function (res) {
      if (res.status === 204) { return null; }
      if (!res.ok) { throw new Error("HTTP " + res.status); }
      return res.text();
    }).then(function (html) {
      if (html) { applyPage(html); }
      failures = 0;
    }).catch(function () {
      failures += 1;
    }).finally(function () {
      inFlight = false;
      schedule();
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { clearTimeout(timer); } else { refresh(); }
  });

  // Votes, comments, names and close/reopen post in the background; the
  // server redirects back to the page, which fetch follows.
  poll.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-ajax]");
    if (!form) { return; }
    e.preventDefault();
    var body;
    try { body = new FormData(form, e.submitter); } catch (err) { body = new FormData(form); }
    if (e.submitter && e.submitter.name && !body.has(e.submitter.name)) {
      body.append(e.submitter.name, e.submitter.value);
    }
    form.setAttribute("aria-busy", "true");
    var busyButton = form.querySelector("[data-busy-label]");
    var idleLabel = busyButton && busyButton.innerHTML;
    if (busyButton) {
      busyButton.textContent = busyButton.dataset.busyLabel;
      busyButton.disabled = true;
    }
    clearTimeout(timer);
    // getAttribute: a button named "action" shadows the form.action property.
    fetch(form.getAttribute("action"), {
      method: "POST",
      body: body,
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    }).then(function (res) {
      if (!res.ok) { throw new Error("HTTP " + res.status); }
      return res.text();
    }).then(function (html) {
      var page = applyPage(html);
      if (!page) { return; }
      if (form.classList.contains("comment-form") || form.classList.contains("name-form")) {
        flashButton(form.querySelector("button"), CHECK + "Saved", 1500);
      }
      if (form.classList.contains("suggest-form")) {
        afterSuggest(form, page);
      }
    }).catch(function () {
      window.location.reload();
    }).finally(function () {
      form.removeAttribute("aria-busy");
      if (busyButton) {
        busyButton.innerHTML = idleLabel;
        busyButton.disabled = false;
      }
      schedule();
    });
  });

  // After adding a restaurant: clear the form, refresh the list of
  // restaurants that can still be added, and show the new card.
  function afterSuggest(form, page) {
    if (page.added.length) { form.reset(); }  // keep a link that failed, so it can be fixed
    var select = document.getElementById("suggest-existing");
    var fresh = page.doc.getElementById("suggest-existing");
    if (select && fresh) { select.replaceWith(fresh); }
    var card = page.added[page.added.length - 1];
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.classList.add("is-new");
      setTimeout(function () { card.classList.remove("is-new"); }, 2500);
    }
  }

  // "closes in 12 min" — counted here so it ticks between refreshes.
  function startCountdown() {
    clearInterval(countdownTimer);
    var el = document.querySelector("[data-closes-at]");
    if (!el) { return; }
    var closesAt = Date.parse(el.dataset.closesAt);
    function tick() {
      var seconds = Math.round((closesAt - Date.now()) / 1000);
      if (seconds <= 0) {
        el.textContent = "(closing…)";
        clearInterval(countdownTimer);
        schedule(1000);
        return;
      }
      var minutes = Math.floor(seconds / 60);
      el.textContent = "(in " + (minutes >= 60
        ? Math.floor(minutes / 60) + " h " + (minutes % 60) + " min"
        : minutes >= 1 ? minutes + " min" : seconds + " s") + ")";
    }
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  syncClosed();
  startCountdown();
  schedule();
})();

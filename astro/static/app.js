/* Transit — front end.
   Stateless: the browser holds the birth data and posts it with each request. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };

  const state = {
    birth: null,      // the payload posted to every endpoint
    place: null,      // the picked place, incl. coordinates + timezone
    tier: "free",
    chart: null,
    whop: null,        // pricing config from /api/config
    plan: null,        // the currently selected plan
    entitlement: null, // what the SERVER says this session may see
  };

  // ---------- place autocomplete ----------

  const placeInput = $("place");
  const suggestionBox = $("suggestions");
  let activeIndex = -1;
  let searchTimer = null;

  function closeSuggestions() {
    suggestionBox.classList.remove("open");
    suggestionBox.innerHTML = "";
    activeIndex = -1;
  }

  function choosePlace(place) {
    state.place = place;
    placeInput.value = place.label;
    $("place-hint").textContent = `${place.timezone} · ${place.latitude.toFixed(2)}, ${place.longitude.toFixed(2)}`;
    closeSuggestions();
  }

  function renderSuggestions(results) {
    suggestionBox.innerHTML = "";
    if (!results.length) return closeSuggestions();

    results.forEach((place, index) => {
      const row = el("div", "suggestion");
      row.appendChild(el("span", null, place.label));
      row.appendChild(el("span", "tz", place.timezone));
      row.addEventListener("mousedown", (event) => {
        event.preventDefault();     // keep focus so blur doesn't close first
        choosePlace(place);
      });
      row.addEventListener("mouseenter", () => {
        activeIndex = index;
        highlight();
      });
      suggestionBox.appendChild(row);
    });
    suggestionBox.classList.add("open");
  }

  function highlight() {
    [...suggestionBox.children].forEach((row, index) =>
      row.classList.toggle("active", index === activeIndex)
    );
  }

  placeInput.addEventListener("input", () => {
    state.place = null;
    $("place-hint").textContent = "";
    clearTimeout(searchTimer);
    const query = placeInput.value.trim();
    if (query.length < 2) return closeSuggestions();

    searchTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/places?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        renderSuggestions(data.results || []);
      } catch {
        closeSuggestions();
      }
    }, 180);
  });

  placeInput.addEventListener("keydown", (event) => {
    const rows = suggestionBox.children;
    if (!suggestionBox.classList.contains("open") || !rows.length) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = (activeIndex + 1) % rows.length;
      highlight();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = (activeIndex - 1 + rows.length) % rows.length;
      highlight();
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      rows[activeIndex].dispatchEvent(new MouseEvent("mousedown"));
    } else if (event.key === "Escape") {
      closeSuggestions();
    }
  });

  placeInput.addEventListener("blur", () => setTimeout(closeSuggestions, 140));

  // ---------- birth time toggle ----------

  $("time-unknown").addEventListener("change", (event) => {
    $("time").disabled = event.target.checked;
  });

  // ---------- views ----------

  function show(view) {
    ["landing", "intake", "loading", "results"].forEach((name) =>
      $(`view-${name}`).classList.toggle("hidden", name !== view)
    );
    // `marketing` gates the nav CTA to the landing page, so app screens keep a
    // single primary action of their own.
    $("nav").classList.toggle("marketing", view === "landing");
    $("nav").classList.toggle("on-sky", view === "landing");
    requestAnimationFrame(syncNav);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function showError(message) {
    const box = $("error");
    box.textContent = message;
    box.classList.add("show");
  }

  // ---------- submit ----------

  $("submit").addEventListener("click", async () => {
    $("error").classList.remove("show");

    const date = $("date").value;
    if (!date) return showError("Please enter your birth date.");
    if (!state.place) return showError("Please pick your birth place from the list.");

    const timeUnknown = $("time-unknown").checked;
    if (!timeUnknown && !$("time").value) {
      return showError("Please enter your birth time, or tick that you don't know it.");
    }

    state.birth = {
      name: $("name").value.trim(),
      date,
      time: timeUnknown ? "12:00" : $("time").value,
      timeKnown: !timeUnknown,
      place: state.place.label,
      latitude: state.place.latitude,
      longitude: state.place.longitude,
      timezone: state.place.timezone,
    };
    state.tier = "free";

    show("loading");
    try {
      const chartResponse = await postJSON("/api/chart", state.birth);
      state.chart = chartResponse;

      $("loading-title").textContent = "Reading your tenth house.";
      $("loading-sub").textContent = "Finding the career placements and the transits crossing them.";

      const reading = await postJSON("/api/reading", state.birth);
      renderResults(chartResponse, reading);
      show("results");
    } catch (error) {
      show("intake");
      showError(error.message || "Something went wrong. Please try again.");
    }
  });

  async function postJSON(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  // ---------- rendering ----------

  function renderResults(chartData, readingData) {
    const content = readingData.content;
    const chart = chartData.chart;
    const timeKnown = chart.birth.timeKnown;

    $("headline").textContent = content.headline;
    $("core-read").textContent = content.core_read;
    $("next-step").textContent = content.next_step;

    const name = chart.birth.name ? `${chart.birth.name} · ` : "";
    const timeLabel = timeKnown ? chart.birth.time : "time unknown";
    $("birth-line").textContent =
      `${name}${chart.birth.date} · ${timeLabel} · ${chart.birth.place} · ` +
      `UTC${chart.utcOffsetHours >= 0 ? "+" : ""}${chart.utcOffsetHours}` +
      `${chart.dstInEffect ? " (DST)" : ""}`;

    $("tier-label").textContent =
      readingData.tier === "paid" ? "Your full career reading" : "Your career reading";
    $("no-time-notice").classList.toggle("hidden", timeKnown);
    $("offline-notice").classList.toggle("hidden", readingData.source !== "offline");

    renderCards($("strengths"), content.strengths, "card");
    renderCards($("friction"), content.friction, "card friction");
    renderTiming(content.timing, chartData.timing);
    renderReceipts(chart);

    $("upsell-block").classList.toggle("hidden", readingData.tier === "paid");
    $("ask-block").classList.toggle("hidden", readingData.tier !== "paid");

    if (readingData.tier !== "paid") {
      renderLockedPreview();
      renderPlans();
    }
  }

  function renderCards(container, items, className) {
    container.innerHTML = "";
    (items || []).forEach((item) => {
      const card = el("div", className);
      card.appendChild(el("h3", null, item.title));
      card.appendChild(el("p", null, item.body));
      if (item.evidence) {
        const evidence = el("div", "evidence");
        evidence.appendChild(el("b", null, "From"));
        evidence.appendChild(el("span", null, item.evidence));
        card.appendChild(evidence);
      }
      container.appendChild(card);
    });
  }

  function renderTiming(entries, timing) {
    const container = $("timing");
    container.innerHTML = "";

    // Index computed windows so each written entry can carry its real tags.
    const windows = (timing && timing.windows) || [];

    (entries || []).forEach((entry) => {
      const row = el("div", "timing-item");
      const when = el("div", "timing-when", entry.dates);

      const match = windows.find(
        (w) => `${w.transiting} ${w.aspect} ${w.natal_point}` === entry.window
      );
      if (match) {
        if (match.activeNow) when.appendChild(makeTag("Active now", "active"));
        if (match.perfects) {
          when.appendChild(makeTag("Exact", "exact", match.exact_dates.join(", ")));
        } else {
          when.appendChild(makeTag("Never exact", "soft"));
        }
      }

      const what = el("div", "timing-what");
      what.appendChild(el("h4", null, entry.window));
      what.appendChild(el("p", null, entry.guidance));
      if (entry.evidence) {
        const evidence = el("div", "evidence");
        evidence.appendChild(el("b", null, "From"));
        evidence.appendChild(el("span", null, entry.evidence));
        what.appendChild(evidence);
      }

      row.appendChild(when);
      row.appendChild(what);
      container.appendChild(row);
    });

    // Mercury retrograde is universally actionable for contracts, so it always
    // gets a row rather than depending on the model to surface it.
    const retrogrades = (timing && timing.mercuryRetrograde) || [];
    if (retrogrades.length) {
      const row = el("div", "timing-item");
      const when = el("div", "timing-when",
        retrogrades.slice(0, 3).map((r) => `${r.start} → ${r.end}`).join("\n"));
      const what = el("div", "timing-what");
      what.appendChild(el("h4", null, "Mercury retrograde"));
      what.appendChild(el("p", null,
        "Traditionally a re-read-the-contract window rather than a sign-it window. " +
        "Not a reason to stall a good offer — a reason to check the details twice."));
      row.appendChild(when);
      row.appendChild(what);
      container.appendChild(row);
    }
  }

  function makeTag(text, kind, data) {
    const tag = el("span", `tag ${kind}`, text);
    if (data) {
      tag.appendChild(document.createTextNode(" "));
      tag.appendChild(el("span", "tag-date", data));
    }
    tag.style.display = "block";
    return tag;
  }

  function renderReceipts(chart) {
    const angles = $("angles");
    angles.innerHTML = "";
    if (chart.birth.timeKnown) {
      [
        ["Midheaven — career point", chart.angles.midheaven.display],
        ["Ascendant", chart.angles.ascendant.display],
      ].forEach(([key, value]) => {
        const box = el("div", "angle");
        box.appendChild(el("div", "k", key));
        box.appendChild(el("div", "v", value));
        angles.appendChild(box);
      });
    }

    const grid = $("receipts");
    grid.innerHTML = "";
    chart.positions.forEach((position) => {
      const row = el("div", "receipt");
      row.appendChild(el("span", "body", position.body));
      const pos = el("span", "pos", position.display);
      if (position.retrograde) pos.classList.add("rx");
      row.appendChild(pos);
      grid.appendChild(row);
    });

    $("receipts-foot").textContent =
      `Julian day ${chart.julianDay} · ${chart.utc} UTC · ` +
      `${chart.houseSystem} houses · Swiss Ephemeris`;
  }

  // ---------- paywall ----------

  /* Blurred skeletons stand in for the locked sections. They are generated
     here rather than sent by the server, so none of the paid reading reaches
     the browser before it is paid for. */
  function renderLockedPreview() {
    const host = $("locked-preview");
    if (!host || host.childElementCount) return;
    [["title", "mid", "short"], ["title", "mid", "mid", "short"], ["title", "short", "mid"]]
      .forEach((lines) => {
        const card = el("div", "skeleton-card");
        lines.forEach((kind) => card.appendChild(el("div", `skeleton-line ${kind}`)));
        host.appendChild(card);
      });
  }

  function renderPlans() {
    const host = $("plans");
    if (!host || host.childElementCount) return;
    const plans = (state.whop && state.whop.plans) || [];

    plans.forEach((plan) => {
      const card = el("button", "plan");
      card.type = "button";
      card.setAttribute("aria-pressed", String(Boolean(plan.highlighted)));
      if (plan.highlighted && plan.trialDays) {
        card.appendChild(el("span", "plan-badge", `${plan.trialDays} days free`));
      }
      card.appendChild(el("span", "plan-name", plan.name));
      card.appendChild(el("span", "plan-price", plan.price));
      card.appendChild(el("span", "plan-cadence", plan.cadence));
      card.appendChild(el("span", "plan-note", plan.note));
      card.addEventListener("click", () => selectPlan(plan.key));
      host.appendChild(card);
      if (plan.highlighted) state.plan = plan;
    });

    if (!state.plan && plans.length) state.plan = plans[0];
    syncPaywallCopy();
  }

  function selectPlan(key) {
    const plans = (state.whop && state.whop.plans) || [];
    state.plan = plans.find((p) => p.key === key) || state.plan;
    [...$("plans").children].forEach((card, index) =>
      card.setAttribute("aria-pressed", String(plans[index] && plans[index].key === key))
    );
    syncPaywallCopy();
  }

  function syncPaywallCopy() {
    const plan = state.plan;
    if (!plan) return;
    $("unlock").textContent = plan.trialDays ? "Start free trial" : `Get ${plan.name.toLowerCase()}`;
    $("paywall-note").textContent = plan.trialDays
      ? `${plan.trialDays} days free, then ${plan.price} ${plan.cadence}.`
      : `${plan.price} ${plan.cadence}.`;
  }

  /* Opening the Whop overlay: append an element carrying the plan id and the
     overlay attribute. The loader installs a MutationObserver, so an element
     added now is picked up and mounted without re-running the script. */
  function openWhopCheckout(checkoutSessionId) {
    document
      .querySelectorAll("[data-whop-checkout-session], [data-whop-checkout-plan-id]")
      .forEach((node) => node.remove());
    const mount = document.createElement("div");
    // The session attribute, not plan-id: only a checkout configuration carries
    // the metadata that links this purchase back to our session token.
    mount.setAttribute("data-whop-checkout-session", checkoutSessionId);
    mount.setAttribute("data-whop-checkout-overlay", "true");
    mount.setAttribute("data-whop-checkout-theme", "light");
    document.body.appendChild(mount);
    return mount;
  }

  /* Re-fetch the reading. Whatever tier comes back is whatever the server says
     this session is entitled to -- the client has no way to ask for more. */
  async function refreshReading() {
    const reading = await postJSON("/api/reading", state.birth);
    state.tier = reading.tier;
    renderResults(state.chart, reading);
    return reading;
  }

  /* After checkout the webhook is a separate server-to-server round trip, so
     entitlement can lag the browser by a moment. Poll briefly rather than
     assuming, and never unlock on the client's say-so. */
  async function awaitEntitlement(attempts = 12, delayMs = 1000) {
    for (let i = 0; i < attempts; i += 1) {
      const response = await fetch("/api/entitlement");
      const access = await response.json().catch(() => ({}));
      if (access.entitled) return access;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    return null;
  }

  async function settleAfterCheckout() {
    const button = $("unlock");
    button.disabled = true;
    button.textContent = "Confirming your subscription…";
    const access = await awaitEntitlement();
    if (!access) {
      button.disabled = false;
      syncPaywallCopy();
      $("paywall-note").textContent =
        "Payment received, but we haven't had confirmation yet. Refresh in a moment.";
      return;
    }
    const reading = await refreshReading();
    if (reading.tier === "paid") {
      $("ask-block").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  /* Claiming a subscription bought outside our own checkout. Those purchases
     carry no session token, so the server records them unowned and the buyer
     binds one to this browser with the membership ID from their receipt. */
  $("claim-toggle").addEventListener("click", () => {
    const form = $("claim-form");
    const opening = form.classList.contains("hidden");
    form.classList.toggle("hidden", !opening);
    $("claim-toggle").setAttribute("aria-expanded", String(opening));
    if (opening) $("claim-id").focus();
  });

  async function submitClaim() {
    const button = $("claim-submit");
    const note = $("claim-note");
    const membershipId = $("claim-id").value.trim();

    note.classList.remove("is-error");
    if (!membershipId) {
      note.textContent = "Enter the membership ID from your Whop receipt.";
      note.classList.add("is-error");
      return;
    }

    button.disabled = true;
    note.textContent = "Checking…";
    try {
      const response = await fetch("/api/claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ membershipId }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        note.textContent = body.error || "That didn't work.";
        note.classList.add("is-error");
        return;
      }
      note.textContent = "Restored. Loading your full reading…";
      const reading = await refreshReading();
      if (reading.tier === "paid") {
        $("ask-block").scrollIntoView({ behavior: "smooth", block: "center" });
      }
    } catch (error) {
      note.textContent = error.message;
      note.classList.add("is-error");
    } finally {
      button.disabled = false;
    }
  }

  $("claim-submit").addEventListener("click", submitClaim);
  $("claim-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitClaim();
  });

  // Whop reports checkout outcomes by posting a message to the host page.
  window.addEventListener("message", async (event) => {
    if (!/whop\.com$/.test(new URL(event.origin).hostname)) return;
    const type = event.data && (event.data.event || event.data.type);
    if (type !== "complete" && type !== "success") return;
    try {
      await settleAfterCheckout();
    } catch (error) {
      alert(`Payment went through, but loading the reading failed: ${error.message}`);
    }
  });

  $("unlock").addEventListener("click", async () => {
    const button = $("unlock");
    const original = button.textContent;

    if (!state.whop || !state.whop.configured || !state.plan) {
      $("paywall-note").textContent =
        "Checkout isn't configured on this server yet.";
      return;
    }

    button.disabled = true;
    button.textContent = "Opening checkout…";
    try {
      // The server mints a checkout configuration carrying this session's
      // token, so the webhook can tell us who paid.
      const checkout = await postJSON("/api/checkout", { plan: state.plan.key });
      if (!window.wco) throw new Error("Checkout script didn't load. Disable your blocker and retry.");
      openWhopCheckout(checkout.checkoutSessionId);
      button.disabled = false;
      button.textContent = original;
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      $("paywall-note").textContent = error.message;
    }
  });

  // ---------- ask ----------

  document.querySelectorAll(".chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      $("question").value = chip.textContent;
      $("question").focus();
    })
  );

  $("ask").addEventListener("click", async () => {
    const question = $("question").value.trim();
    if (!question) return;

    const button = $("ask");
    const answer = $("answer");
    button.disabled = true;
    button.textContent = "Thinking…";
    answer.classList.add("show");
    answer.textContent = "";

    const cursor = el("span", "cursor");
    answer.appendChild(cursor);

    try {
      const response = await fetch("/api/question", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...state.birth, question }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Request failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let text = "";

      // Server-sent events: frames are separated by a blank line, and a frame
      // can straddle a chunk boundary, so keep the remainder in the buffer.
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (payload === "[DONE]") continue;
          try {
            const parsed = JSON.parse(payload);
            if (parsed.error) throw new Error(parsed.error);
            text += parsed.text || "";
            answer.textContent = text;
            answer.appendChild(cursor);
          } catch (parseError) {
            if (parseError instanceof SyntaxError) continue;
            throw parseError;
          }
        }
      }
      cursor.remove();
    } catch (error) {
      answer.textContent = `Couldn't get an answer: ${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "Ask";
    }
  });

  // ---------- restart ----------

  $("restart").addEventListener("click", () => {
    state.tier = "free";
    $("answer").classList.remove("show");
    $("question").value = "";
    show("intake");
  });

  // ---------- nav ----------

  /* The single CTA, repeated in the nav, the hero, and the closing section.
     Every one of them does the same thing: open the chart form. */
  document.querySelectorAll(".nav-cta, .hero-cta").forEach((button) =>
    button.addEventListener("click", () => {
      show("intake");
      setTimeout(() => $("date").focus({ preventScroll: true }), 420);
    })
  );

  $("home").addEventListener("click", () => show("landing"));

  const dropdown = $("dropdown");
  const dropdownToggle = $("dropdown-toggle");
  const dropdownMenu = $("dropdown-menu");

  function setDropdown(open) {
    dropdownMenu.classList.toggle("open", open);
    dropdownToggle.classList.toggle("dropdown-toggle-open", open);
    dropdownToggle.setAttribute("aria-expanded", String(open));
  }

  dropdownToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    setDropdown(!dropdownMenu.classList.contains("open"));
  });

  dropdownMenu.addEventListener("click", () => setDropdown(false));
  document.addEventListener("click", (event) => {
    if (!dropdown.contains(event.target)) setDropdown(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setDropdown(false);
  });

  // In-page anchors only mean anything on the landing view.
  document.querySelectorAll('a[href^="#"]').forEach((link) =>
    link.addEventListener("click", (event) => {
      const target = document.getElementById(link.getAttribute("href").slice(1));
      if (!target) return;
      event.preventDefault();
      if ($("view-landing").classList.contains("hidden")) show("landing");
      requestAnimationFrame(() =>
        target.scrollIntoView({ behavior: "smooth", block: "start" })
      );
    })
  );

  function syncNav() {
    const nav = $("nav");
    const sky = document.querySelector(".sky");
    // The inverted treatment only holds while the nav is actually over the dark
    // hero; scrolling past it on the landing page hands the nav back to cream,
    // otherwise it would be light text on a light ground.
    const overSky =
      nav.classList.contains("marketing") &&
      sky &&
      window.scrollY < sky.offsetHeight - nav.offsetHeight - 12;
    nav.classList.toggle("on-sky", Boolean(overSky));
    nav.classList.toggle("scrolled", window.scrollY > 8 && !overSky);
  }

  window.addEventListener("scroll", syncNav, { passive: true });

  // ---------- starfield ----------

  /* Generated rather than shipped as an image: no asset to load, it scales to
     any viewport, and it is the sky the charts are actually calculated from. */
  function startStarfield() {
    const canvas = $("starfield");
    if (!canvas) return;
    const context = canvas.getContext("2d");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let stars = [];
    let frame = null;

    function build() {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const { width, height } = canvas.getBoundingClientRect();
      if (!width || !height) return;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);

      // Denser toward the top: the sky fades into the warm horizon below, so
      // stars there would fight the glow.
      const count = Math.round((width * height) / 5200);
      stars = Array.from({ length: count }, () => {
        const depth = Math.pow(Math.random(), 1.7);
        return {
          x: Math.random() * width,
          y: depth * height * 0.92,
          r: 0.35 + Math.random() * 1.15,
          base: 0.16 + Math.random() * 0.5,
          phase: Math.random() * Math.PI * 2,
          speed: 0.4 + Math.random() * 0.9,
        };
      });
    }

    function draw(time) {
      const { width, height } = canvas.getBoundingClientRect();
      context.clearRect(0, 0, width, height);
      for (const star of stars) {
        // Fade stars out as they approach the horizon glow.
        const fade = 1 - Math.min(1, Math.max(0, (star.y / height - 0.55) / 0.45));
        const twinkle = still ? 1 : 0.72 + 0.28 * Math.sin(time / 1400 * star.speed + star.phase);
        context.globalAlpha = star.base * twinkle * fade;
        context.fillStyle = "#fdf8ee";
        context.beginPath();
        context.arc(star.x, star.y, star.r, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;
      if (!still) frame = requestAnimationFrame(draw);
    }

    function restart() {
      build();
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    }

    restart();
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(restart, 180);
    });

    // Don't burn frames on a canvas nobody is looking at.
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && frame) {
        cancelAnimationFrame(frame);
        frame = null;
      } else if (!document.hidden && !frame && !still) {
        frame = requestAnimationFrame(draw);
      }
    });
  }

  startStarfield();
  $("nav").classList.add("marketing", "on-sky");

  // ---------- boot ----------

  fetch("/api/config")
    .then((response) => response.json())
    .then((config) => {
      state.whop = config.whop || null;
      fetch("/api/entitlement")
        .then((r) => r.json())
        .then((access) => { state.entitlement = access; })
        .catch(() => {});
      if (!config.aiConfigured) {
        $("engine-note").textContent =
          "Swiss Ephemeris · calculated locally · template reader";
      }
    })
    .catch(() => {});
})();

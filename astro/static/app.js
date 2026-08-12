/* Northstar — front end.
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
    reading: null,     // fetched lazily when the full chart is opened
    dashboard: null,
    whop: null,        // pricing config from /api/config
    plan: null,        // the currently selected plan
    entitlement: null, // what the SERVER says this session may see
  };

  // ---------- place autocomplete ----------

  const placeInput = $("place");
  const suggestionBox = $("suggestions");
  let activeIndex = -1;
  let searchTimer = null;

  function setPlaceHint(message, isProblem) {
    const hint = $("place-hint");
    hint.textContent = message;
    hint.classList.toggle("is-problem", Boolean(isProblem));
  }

  function closeSuggestions() {
    suggestionBox.classList.remove("open", "flip-up");
    suggestionBox.style.maxHeight = "";
    suggestionBox.innerHTML = "";
    activeIndex = -1;
  }

  function choosePlace(place) {
    state.place = place;
    placeInput.value = place.label;
    setPlaceHint(`${place.timezone} · ${place.latitude.toFixed(2)}, ${place.longitude.toFixed(2)}`, false);
    closeSuggestions();
  }

  /* Put the list where it can actually be reached.
     It is absolutely positioned under the input, and on a standard laptop the
     birth-place field sits low enough that the list opened past the bottom of
     the window -- rendered, clickable, and completely invisible. So: scroll it
     into view when there is room to scroll, and flip it above the input when
     there is not. */
  function positionSuggestions() {
    const GAP = 6;        // matches the CSS offset
    const MARGIN = 12;    // breathing room against the window edge
    const MIN_HEIGHT = 140;

    suggestionBox.classList.remove("flip-up");
    suggestionBox.style.maxHeight = "";

    const field = placeInput.getBoundingClientRect();
    const wanted = Math.min(suggestionBox.scrollHeight, 258);
    const spaceBelow = window.innerHeight - field.bottom - GAP - MARGIN;
    const spaceAbove = field.top - GAP - MARGIN;
    const scrollable = Math.max(
      0,
      document.documentElement.scrollHeight - window.innerHeight - window.scrollY
    );

    if (spaceBelow + scrollable >= Math.min(wanted, MIN_HEIGHT)) {
      const height = Math.min(wanted, spaceBelow + scrollable);
      suggestionBox.style.maxHeight = `${height}px`;
      const overflow = height - spaceBelow;
      if (overflow > 0) {
        window.scrollBy({ top: Math.min(overflow, scrollable), behavior: "smooth" });
      }
    } else if (spaceAbove >= MIN_HEIGHT) {
      suggestionBox.classList.add("flip-up");
      suggestionBox.style.maxHeight = `${Math.min(wanted, spaceAbove)}px`;
    } else {
      suggestionBox.style.maxHeight = `${Math.max(MIN_HEIGHT, spaceBelow)}px`;
    }
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
    positionSuggestions();
  }

  function highlight() {
    [...suggestionBox.children].forEach((row, index) =>
      row.classList.toggle("active", index === activeIndex)
    );
  }

  placeInput.addEventListener("input", () => {
    state.place = null;
    setPlaceHint("", false);
    clearTimeout(searchTimer);
    const query = placeInput.value.trim();
    if (query.length < 2) return closeSuggestions();

    searchTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/places?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error(`city lookup returned ${response.status}`);
        const data = await response.json();
        const results = data.results || [];
        if (!results.length) {
          /* A real query with no match is information, not silence. */
          setPlaceHint(
            `No city matching "${query}". Try the nearest large town, or a different spelling.`,
            true
          );
          return closeSuggestions();
        }
        renderSuggestions(results);
      } catch (error) {
        /* Swallowing this was the whole bug: the field looked like a plain
           text input with no dropdown and no reason given. */
        console.error("city lookup failed:", error);
        setPlaceHint(
          "Can't reach the city list right now — type your city and we'll look it up when you continue.",
          true
        );
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

  window.addEventListener("resize", () => {
    if (suggestionBox.classList.contains("open")) positionSuggestions();
  });

  // ---------- birth time toggle ----------

  $("time-unknown").addEventListener("change", (event) => {
    $("time").disabled = event.target.checked;
  });

  // ---------- views ----------

  function show(view) {
    ["landing", "intake", "loading", "dashboard", "results"].forEach((name) =>
      $(`view-${name}`).classList.toggle("hidden", name !== view)
    );
    // `marketing` gates the nav CTA to the landing page, so app screens keep a
    // single primary action of their own.
    $("nav").classList.toggle("marketing", view === "landing");
    $("nav").classList.toggle("on-sky", view === "landing");
    document.body.classList.toggle("app-sky", view !== "landing");
    if (view !== "landing") drawNight();
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

    const typedPlace = $("place").value.trim();
    if (!state.place && !typedPlace) {
      return showError("Please enter your birth place.");
    }

    const timeUnknown = $("time-unknown").checked;
    if (!timeUnknown && !$("time").value) {
      return showError("Please enter your birth time, or tick that you don't know it.");
    }

    state.birth = {
      name: $("name").value.trim(),
      date,
      time: timeUnknown ? "12:00" : $("time").value,
      timeKnown: !timeUnknown,
      /* If nothing was picked from the list, send the typed name alone and let
         the server resolve it. It has the same city index the dropdown uses, so
         a working picker is a convenience rather than a requirement. */
      place: state.place ? state.place.label : typedPlace,
      latitude: state.place ? state.place.latitude : null,
      longitude: state.place ? state.place.longitude : null,
      timezone: state.place ? state.place.timezone : "",
    };
    state.tier = "free";
    state.reading = null;

    show("loading");
    try {
      const chartResponse = await postJSON("/api/chart", state.birth);
      state.chart = chartResponse;

      $("loading-title").textContent = "Reading your tenth house.";
      $("loading-sub").textContent = "Finding the career placements and the transits crossing them.";

      const dashboard = await postJSON("/api/dashboard", state.birth);
      state.tier = dashboard.tier;
      state.dashboard = dashboard;
      renderDashboard(dashboard, chartResponse);
      show("dashboard");
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

  /* One six-line block is a wall; the same sentences in pairs are a read.
     Splits on sentence ends, keeping abbreviations and decimals intact, then
     groups them so no paragraph runs longer than about three lines. */
  function paragraphs(text, perParagraph = 2) {
    const sentences = String(text || "")
      .split(/(?<=[.!?])\s+(?=[A-Z"'\u201c])/)
      .map((s) => s.trim())
      .filter(Boolean);

    const groups = [];
    for (let i = 0; i < sentences.length; i += perParagraph) {
      groups.push(sentences.slice(i, i + perParagraph).join(" "));
    }
    return groups.length ? groups : [String(text || "")];
  }

  function renderProse(container, text) {
    container.innerHTML = "";
    paragraphs(text).forEach((chunk) => container.appendChild(el("p", null, chunk)));
    return container;
  }

  // ---------- night sky ----------

  /* The app screens' celestial ground. Navy at 4-12% alpha, behind everything,
     so it reads as atmosphere without touching the contrast of a single word.
     Generated rather than shipped: no asset, and it re-renders to any size. */
  function drawNight() {
    const canvas = $("night");
    if (!canvas) return;
    const context = canvas.getContext("2d");
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = window.innerWidth;
    const height = window.innerHeight;

    canvas.width = width * ratio;
    canvas.height = height * ratio;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    /* Deterministic from the viewport size, so a resize does not reshuffle the
       sky under the reader. */
    let seed = Math.round(width * 7 + height * 13);
    const random = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };

    const count = Math.round((width * height) / 9000);
    for (let i = 0; i < count; i += 1) {
      const x = random() * width;
      const y = random() * height;
      const radius = 0.45 + random() * 1.15;
      // Denser toward the top, where the navy wash already sits.
      const falloff = 1 - (y / height) * 0.55;
      context.beginPath();
      context.fillStyle = `rgba(31, 42, 68, ${(0.09 + random() * 0.13) * falloff})`;
      context.arc(x, y, radius, 0, Math.PI * 2);
      context.fill();
    }

    // A handful of four-point sparkles, gold, barely there.
    for (let i = 0; i < 11; i += 1) {
      const x = random() * width;
      const y = random() * height * 0.7;
      const arm = 3 + random() * 4;
      context.save();
      context.translate(x, y);
      context.strokeStyle = `rgba(201, 162, 75, ${0.22 + random() * 0.16})`;
      context.lineWidth = 1.0;
      context.beginPath();
      context.moveTo(-arm, 0); context.lineTo(arm, 0);
      context.moveTo(0, -arm); context.lineTo(0, arm);
      context.stroke();
      context.restore();
    }
  }

  let nightTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(nightTimer);
    nightTimer = setTimeout(drawNight, 180);
  });

  // ---------- dashboard ----------

  /* A drawn lock rather than an emoji: it inherits colour, scales with the
     type, and renders identically everywhere. */
  function lockIcon() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "lock");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2.4");
    svg.setAttribute("aria-hidden", "true");
    const body = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    body.setAttribute("x", "4"); body.setAttribute("y", "10.5");
    body.setAttribute("width", "16"); body.setAttribute("height", "10.5");
    body.setAttribute("rx", "2");
    const shackle = document.createElementNS("http://www.w3.org/2000/svg", "path");
    shackle.setAttribute("d", "M8 10.5V7a4 4 0 0 1 8 0v3.5");
    svg.append(body, shackle);
    return svg;
  }

  function renderDashboard(data, chartData) {
    const chart = chartData.chart;

    // 1. Archetype
    $("dash-archetype").textContent = data.archetype.name;
    $("dash-archetype-line").textContent = data.archetype.line;

    const name = chart.birth.name ? `${chart.birth.name} · ` : "";
    const timeLabel = chart.birth.timeKnown ? chart.birth.time : "time unknown";
    $("dash-birth-line").textContent =
      `${name}${chart.birth.date} · ${timeLabel} · ${chart.birth.place}`;

    renderPrecision(data.precision);
    renderSystems(data.systems, data.precision);
    renderTabs(data.tabs);
    renderTimingBuckets(data.timing, data.tier);

    $("dash-next-step").textContent = data.nextStep || "";
    $("dash-next-block").classList.toggle("hidden", !data.nextStep);
  }

  /* 4. Missing birth time. Framed as a layer that is switched off and can be
     switched on, not as an error the user has made. */
  function renderPrecision(precision) {
    const block = $("dash-precision-block");
    if (precision.exact) return block.classList.add("hidden");

    block.classList.remove("hidden");
    $("precision-headline").textContent = precision.headline;
    $("precision-body").textContent = precision.body;
    $("precision-note").textContent = precision.note;
    $("precision-cta").textContent = precision.cta;

    const list = $("precision-list");
    list.innerHTML = "";
    (precision.unlocks || []).forEach((item) => list.appendChild(el("li", null, item)));
  }

  /* 2. The layers of chart data this reading is actually built from. */
  function renderSystems(systems, precision) {
    $("systems-intro").textContent = precision.exact
      ? "Every layer below was calculated from your birth moment. Each one feeds a different part of your reading."
      : "Calculated from your birth date and place. One layer needs an exact time and is currently switched off.";

    const container = $("systems");
    container.innerHTML = "";

    systems.forEach((system) => {
      const card = el("div", `system${system.status === "needs_time" ? " is-off" : ""}`);
      card.appendChild(el("div", "system-source", system.source));
      card.appendChild(el("div", "system-name", system.name));
      card.appendChild(el("p", "system-read", system.read));

      const more = el("button", "link-button system-more",
        system.more === "time" ? "Add your birth time" : "Read more");
      more.type = "button";
      more.addEventListener("click", () => {
        if (system.more === "time") return startOver();
        if (system.more === "timing") {
          return $("dash-timing-block").scrollIntoView({ behavior: "smooth", block: "start" });
        }
        openFullChart();
      });
      card.appendChild(more);
      container.appendChild(card);
    });
  }

  /* 3. The reading, split into tabs. */
  function renderTabs(tabs) {
    const tablist = $("tablist");
    const panels = $("tabpanels");
    tablist.innerHTML = "";
    panels.innerHTML = "";

    tabs.forEach((tab, index) => {
      const button = el("button", "tab", tab.label);
      button.type = "button";
      button.id = `tab-${tab.key}`;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", `panel-${tab.key}`);
      button.setAttribute("aria-selected", String(index === 0));
      button.tabIndex = index === 0 ? 0 : -1;

      const panel = el("div", `tabpanel${index === 0 ? " is-active" : ""}`);
      panel.id = `panel-${tab.key}`;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", `tab-${tab.key}`);

      if (tab.kind === "items") {
        renderCards(panel, tab.content, "card");
      } else {
        panel.appendChild(renderProse(el("div", "prose"), tab.content));
      }

      button.addEventListener("click", () => selectTab(tab.key));
      button.addEventListener("keydown", (event) => {
        const keys = { ArrowRight: 1, ArrowLeft: -1 };
        if (!(event.key in keys)) return;
        event.preventDefault();
        const next = (index + keys[event.key] + tabs.length) % tabs.length;
        selectTab(tabs[next].key);
        $(`tab-${tabs[next].key}`).focus();
      });

      tablist.appendChild(button);
      panels.appendChild(panel);
    });
  }

  function selectTab(key) {
    [...$("tablist").children].forEach((button) => {
      const active = button.id === `tab-${key}`;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    [...$("tabpanels").children].forEach((panel) =>
      panel.classList.toggle("is-active", panel.id === `panel-${key}`)
    );
  }

  /* 5. Timing. A locked bucket still shows its title and a real teaser --
     never an empty box, and never an invented number. */
  function renderTimingBuckets(buckets, tier) {
    const container = $("timing-buckets");
    container.innerHTML = "";

    buckets.forEach((bucket) => {
      const card = el("div", `bucket${bucket.locked ? " is-locked" : ""}`);

      const head = el("div", "bucket-head");
      head.appendChild(el("span", "bucket-label", bucket.label));
      if (bucket.locked) {
        head.appendChild(lockIcon());
      } else {
        head.appendChild(el("span", "bucket-count",
          bucket.count === 1 ? "1 window" : `${bucket.count} windows`));
      }
      card.appendChild(head);

      card.appendChild(el("p", "bucket-teaser", bucket.teaser));

      if (!bucket.locked) {
        const entries = el("div", "bucket-entries");
        (bucket.entries || []).forEach((entry) => {
          const row = el("div", "bucket-entry");
          row.appendChild(el("div", "t", entry.title));
          row.appendChild(el("div", "d", entry.dates));
          row.appendChild(el("div", "m", entry.meaning));
          entries.appendChild(row);
        });
        if (!(bucket.entries || []).length) {
          entries.appendChild(el("div", "bucket-empty", "Nothing scheduled in this period."));
        }
        card.appendChild(entries);
      }

      container.appendChild(card);
    });

    const locked = buckets.some((b) => b.locked);
    $("timing-upsell").classList.toggle("hidden", !locked);
    if (locked) {
      /* Deliberately not the sum of the three buckets: they answer different
         questions and overlap, so adding them would overstate the number. */
      const total = state.dashboard ? state.dashboard.totalWindows : 0;
      const months = state.dashboard ? state.dashboard.horizonMonths : 18;
      $("timing-upsell-copy").textContent = total
        ? `${total} window${total === 1 ? " is" : "s are"} already calculated across the next ${months} months, with the exact days ${total === 1 ? "it lands" : "they land"}.`
        : `Unlock the full ${months}-month calendar, your Saturn return, and every window as it opens.`;
    }
  }

  async function openFullChart() {
    if (!state.chart) return;
    const button = $("dash-view-chart");
    const original = button.textContent;
    try {
      if (!state.reading) {
        button.disabled = true;
        button.textContent = "Opening…";
        // Served from the same cache the dashboard used, so this is free.
        state.reading = await postJSON("/api/reading", state.birth);
      }
      renderResults(state.chart, state.reading);
      show("results");
    } catch (error) {
      showError(error.message || "Couldn't open your full chart.");
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  /* Sending someone back to the form is how they add a birth time, since the
     app deliberately stores nothing between visits. */
  function startOver() {
    state.tier = "free";
    state.reading = null;
    state.dashboard = null;
    $("time-unknown").checked = false;
    $("time").disabled = false;
    show("intake");
    setTimeout(() => $("time").focus(), 320);
  }

  $("dash-view-chart").addEventListener("click", openFullChart);
  $("precision-cta").addEventListener("click", () => startOver());
  $("timing-unlock").addEventListener("click", () => {
    show("results");
    setTimeout(() => $("upsell-block").scrollIntoView({ behavior: "smooth", block: "center" }), 60);
  });

  // ---------- rendering ----------

  function setFoldMeta(id, text) {
    const node = $(id);
    if (node) node.textContent = text;
  }

  function countLabel(n, one, many) {
    return `${n} ${n === 1 ? one : many}`;
  }

  function renderResults(chartData, readingData) {
    const content = readingData.content;
    const chart = chartData.chart;
    const timeKnown = chart.birth.timeKnown;

    $("headline").textContent = content.headline;
    renderProse($("core-read"), content.core_read);
    $("next-step").textContent = content.next_step;

    /* Each folded section says what is inside, so a closed one is still
       informative rather than a mystery box. */
    const sentences = paragraphs(content.core_read).length;
    setFoldMeta("read-meta", `${sentences} ${sentences === 1 ? "part" : "parts"}`);
    setFoldMeta("strengths-meta", countLabel(content.strengths.length, "strength", "strengths"));
    setFoldMeta("friction-meta", countLabel(content.friction.length, "friction point", "friction points"));
    setFoldMeta("timing-meta", countLabel(content.timing.length, "window", "windows"));

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

/* Tenth House — front end.
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
    ["intake", "loading", "results"].forEach((name) =>
      $(`view-${name}`).classList.toggle("hidden", name !== view)
    );
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

      $("loading-title").textContent = "Reading your chart…";
      $("loading-sub").textContent = "Interpreting the career placements and current transits.";

      const reading = await postJSON("/api/reading", { ...state.birth, tier: "free" });
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
          when.appendChild(makeTag(`Exact ${match.exact_dates.join(", ")}`, "exact"));
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

  function makeTag(text, kind) {
    const tag = el("span", `tag ${kind}`, text);
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

  // ---------- unlock ----------

  $("unlock").addEventListener("click", async () => {
    const button = $("unlock");
    button.disabled = true;
    button.textContent = "Unlocking…";
    try {
      const reading = await postJSON("/api/reading", { ...state.birth, tier: "paid" });
      state.tier = "paid";
      renderResults(state.chart, reading);
      $("ask-block").scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (error) {
      button.disabled = false;
      button.textContent = "Unlock the full reading";
      alert(error.message);
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

  // ---------- boot ----------

  fetch("/api/config")
    .then((response) => response.json())
    .then((config) => {
      if (!config.aiConfigured) {
        $("engine-note").textContent =
          "Swiss Ephemeris · calculated locally · template reader";
      }
    })
    .catch(() => {});
})();

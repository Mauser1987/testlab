/* DCS dataset plot (M2A). Plotly is served by TestLab (static/vendor/plotly).
 *
 * The server sends at most a few thousand points per signal: the full
 * resolution when it fits, otherwise the minimum and maximum of each time
 * bucket, so excursions stay visible. Nothing here knows particular signal
 * names, colours or limits; the only default is by unit: signals with the
 * most common unit start on the left axis, the others on the right axis.
 * The viewer's choice of signals and axes is remembered in this browser.
 *
 * "Add plot to Result" (M2B) sends the definition of what is on screen —
 * signals and axes, time window, axis ranges, caption — with a report image
 * drawn from that definition by the same figure code. Opened from a Result
 * plot (?plot=<id>), the viewer starts from the stored definition instead.
 */
(function () {
  "use strict";
  var config = window.TESTLAB_DCS;
  var signals = JSON.parse(document.getElementById("dcs-signals").textContent);
  var plot = document.getElementById("dcs-plot");
  var status = document.getElementById("plot-status");
  var list = document.querySelector(".signal-list");
  var traces = {}; // column → {x, y} as received
  var toResultConfig = document.getElementById("dcs-plot-to-result");
  toResultConfig = toResultConfig ? JSON.parse(toResultConfig.textContent) : null;
  var stored = toResultConfig && toResultConfig.plot; // a Result plot opened for redrawing
  var state = stored ? fromDefinition(stored) : load() || defaults();
  var initialRanges = stored ? { x: stored.time_range, y: stored.y_range, y2: stored.y2_range } : null;
  var REPORT = { width: 1200, height: 600, scale: 2 }; // report image: 2400 × 1200 px

  function fromDefinition(definition) {
    var result = defaults();
    signals.forEach(function (s) { result.shown[s.column] = false; });
    definition.signals.forEach(function (s) {
      result.shown[s.column] = true;
      result.axis[s.column] = s.axis;
    });
    return result;
  }

  function defaults() {
    var counts = {};
    signals.forEach(function (s) { counts[s.unit] = (counts[s.unit] || 0) + 1; });
    var primary = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0];
    var result = { shown: {}, axis: {} };
    signals.forEach(function (s) {
      result.shown[s.column] = true;
      result.axis[s.column] = s.unit === primary ? "y" : "y2";
    });
    return result;
  }

  function load() {
    try {
      var saved = JSON.parse(window.localStorage.getItem(config.storageKey));
      if (saved && saved.shown && saved.axis) return saved;
    } catch (error) { /* storage unavailable: defaults */ }
    return null;
  }

  function save() {
    try { window.localStorage.setItem(config.storageKey, JSON.stringify(state)); } catch (error) { /* ignore */ }
  }

  function axisTitle(axis) {
    var units = [];
    signals.forEach(function (s) {
      if (state.shown[s.column] && state.axis[s.column] === axis && s.unit && units.indexOf(s.unit) < 0) units.push(s.unit);
    });
    return units.join(", ");
  }

  function figure(source, report, ranges) {
    source = source || traces;
    var data = signals.filter(function (s) { return state.shown[s.column] && source[s.column]; }).map(function (s) {
      return {
        type: "scatter", mode: "lines", name: s.label,
        x: source[s.column].x, y: source[s.column].y,
        yaxis: state.axis[s.column], connectgaps: false,
        hovertemplate: "%{y}<extra>" + s.label.replace(/</g, "&lt;") + "</extra>",
        line: { width: 1.5 }
      };
    });
    var layout = {
      font: { family: '"Segoe UI", Arial, Helvetica, sans-serif', size: 12, color: "#1a1f2b" },
      paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff",
      margin: { t: 16, r: 64, b: 40, l: 64 },
      hovermode: "x unified",
      xaxis: { title: { text: config.timeLabel }, rangeslider: { thickness: 0.08 }, gridcolor: "#eef0f3", zeroline: false },
      yaxis: { title: { text: axisTitle("y") }, gridcolor: "#eef0f3", zeroline: false },
      yaxis2: { title: { text: axisTitle("y2") }, overlaying: "y", side: "right", showgrid: false, zeroline: false },
      legend: { orientation: "h", x: 0, y: -0.28, font: { size: 11 } },
      uirevision: "keep" // keeps zoom while signals or axes change
    };
    if (ranges) {
      if (ranges.x) layout.xaxis.range = ranges.x.slice();
      if (ranges.y) layout.yaxis.range = ranges.y.slice();
      if (ranges.y2) layout.yaxis2.range = ranges.y2.slice();
    }
    if (report) {
      delete layout.xaxis.rangeslider;
      delete layout.uirevision;
      layout.width = REPORT.width; layout.height = REPORT.height;
      layout.margin = { t: 16, r: 72, b: 64, l: 72 };
      layout.legend = { orientation: "h", x: 0, y: -0.14, font: { size: 11 } };
      data.forEach(function (trace) { trace.line.width = 1.2; });
    }
    return { data: data, layout: layout };
  }

  function draw() {
    var fig = figure(null, false, initialRanges);
    initialRanges = null; // only the first drawing; afterwards the viewer keeps the user's zoom
    Plotly.react(plot, fig.data, fig.layout, { responsive: true, displaylogo: false, scrollZoom: true });
  }

  // ---- Add plot to Result ------------------------------------------------------------

  function explicitRange(axis, asShown) {
    // asShown: the range on screen even when automatic (Plotly scales automatic
    // axes over the whole recording, not over the zoomed time window).
    var a = asShown ? plot._fullLayout && plot._fullLayout[axis] : plot.layout && plot.layout[axis];
    if (!a || (!asShown && a.autorange !== false) || !a.range) return null;
    var low = Number(a.range[0]), high = Number(a.range[1]);
    return isFinite(low) && isFinite(high) && low < high ? [low, high] : null;
  }

  function currentDefinition(caption) {
    var shown = signals.filter(function (s) { return state.shown[s.column]; });
    var axes = {};
    shown.forEach(function (s) { axes[state.axis[s.column]] = true; });
    var window = explicitRange("xaxis");
    return {
      signals: shown.map(function (s) { return { column: s.column, axis: state.axis[s.column] }; }),
      time_range: window,
      y_range: axes.y ? explicitRange("yaxis", !!window) : null,
      y2_range: axes.y2 ? explicitRange("yaxis2", !!window) : null,
      caption: caption
    };
  }

  function reportImage(definition) {
    // The window at report resolution, then the same figure as on screen, fixed size.
    var query = "?points=" + toResultConfig.reportPoints + "&columns=" +
      definition.signals.map(function (s) { return s.column; }).join(",");
    if (definition.time_range) query += "&start=" + definition.time_range[0] + "&end=" + definition.time_range[1];
    return fetch(config.dataUrl + query, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        var source = {};
        payload.traces.forEach(function (t) { source[t.column] = { x: t.x, y: t.y }; });
        var fig = figure(source, true, { x: definition.time_range, y: definition.y_range, y2: definition.y2_range });
        return Plotly.toImage({ data: fig.data, layout: fig.layout, config: { staticPlot: true } },
          { format: "png", width: REPORT.width, height: REPORT.height, scale: REPORT.scale });
      })
      .then(function (url) { return fetch(url).then(function (r) { return r.blob(); }); });
  }

  function setupToResult() {
    var panel = document.getElementById("plot-to-result");
    if (!panel || !toResultConfig) return;
    var note = document.getElementById("plot-to-result-status");
    var caption = document.getElementById("plot-caption");
    var buttons = panel.querySelectorAll("[data-plot-action]");
    var csrf = panel.querySelector("input[name=csrfmiddlewaretoken]").value;

    function busy(on) { buttons.forEach(function (b) { b.disabled = on; }); }

    function send(action) {
      var definition = currentDefinition(caption.value.trim());
      if (!definition.signals.length) { note.textContent = "Select at least one signal to plot."; return; }
      busy(true);
      note.textContent = "Drawing the report image…";
      reportImage(definition).then(function (image) {
        var body = new FormData();
        body.append("definition", JSON.stringify(definition));
        body.append("image", image, "plot.png");
        var url = action === "update" ? toResultConfig.updateUrl : toResultConfig.addUrl;
        return fetch(url, { method: "POST", body: body, credentials: "same-origin", headers: { "X-CSRFToken": csrf } })
          .then(function (response) {
            return response.json().catch(function () { return { error: "HTTP " + response.status }; })
              .then(function (payload) { if (!response.ok) throw new Error(payload.error || "HTTP " + response.status); return payload; });
          });
      }).then(function (payload) {
        note.textContent = payload.message + " ";
        var link = document.createElement("a");
        link.href = payload.result_url; link.textContent = "Open in Result";
        note.appendChild(link);
      }).catch(function (error) {
        note.textContent = "The plot was not added: " + error.message;
      }).then(function () { busy(false); });
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function () { send(button.dataset.plotAction); });
    });
  }

  function syncControls() {
    list.querySelectorAll("li").forEach(function (item) {
      var column = item.dataset.column;
      item.querySelector("input.show").checked = !!state.shown[column];
      item.querySelectorAll("[data-axis]").forEach(function (button) {
        button.classList.toggle("active", state.axis[column] === button.dataset.axis);
        button.setAttribute("aria-pressed", state.axis[column] === button.dataset.axis);
      });
    });
  }

  function fetchAll() {
    var columns = signals.map(function (s) { return s.column; }).join(",");
    return fetch(config.dataUrl + "?columns=" + columns, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        payload.traces.forEach(function (t) { traces[t.column] = { x: t.x, y: t.y }; });
        status.textContent = payload.decimated
          ? payload.samples_in_window + " samples per signal, shown as min/max of time buckets (" +
            payload.points_per_signal + " points); the stored data keeps every sample"
          : "All " + payload.samples_in_window + " samples per signal";
      });
  }

  list.addEventListener("change", function (event) {
    if (!event.target.matches("input.show")) return;
    state.shown[event.target.closest("li").dataset.column] = event.target.checked;
    save(); draw();
  });
  list.addEventListener("click", function (event) {
    var button = event.target.closest("[data-axis]");
    if (!button) return;
    state.axis[button.closest("li").dataset.column] = button.dataset.axis;
    syncControls(); save(); draw();
  });
  document.querySelectorAll("[data-select]").forEach(function (button) {
    button.addEventListener("click", function () {
      signals.forEach(function (s) { state.shown[s.column] = button.dataset.select === "all"; });
      syncControls(); save(); draw();
    });
  });

  syncControls();
  setupToResult();
  fetchAll().then(draw).catch(function (error) {
    status.textContent = "The plot data could not be loaded (" + error.message + ").";
  });
})();

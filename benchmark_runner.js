const runnerStatus = document.getElementById("runner-status");

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const element = byId(id);
  if (element) {
    element.textContent = value;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatDecimal(value, digits = 2) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercent(value) {
  return `${formatDecimal(value, 2)}%`;
}

function formatDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

async function jsonRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.ok === false) {
    throw new Error(body.detail || body.message || `Request failed: ${response.status}`);
  }
  return body;
}

function setBusy(message) {
  if (runnerStatus) {
    runnerStatus.textContent = message;
  }
}

function renderOverview(overview = {}) {
  setText("runner-total-runs", formatNumber(overview.total_benchmark_runs));
  setText("runner-total-workflows", formatNumber(overview.total_workflows));
  setText("runner-success-rate", formatPercent(overview.success_rate));
  setText("runner-failure-rate", formatPercent(overview.failure_rate));
  setText("runner-reliability-score", formatDecimal(overview.reliability_score, 2));
  setText("runner-last-updated", `Last updated: ${formatDate(overview.last_updated)}`);
}

function lineChart(points, field, color) {
  if (!points.length) {
    return `<div class="empty">No benchmark data yet. Run a benchmark or generate sample data.</div>`;
  }
  const width = 360;
  const height = 160;
  const pad = 22;
  const ordered = [...points].reverse();
  const maxValue = 100;
  const coords = ordered.map((point, index) => {
    const x = ordered.length === 1 ? width / 2 : pad + (index / (ordered.length - 1)) * (width - pad * 2);
    const y = height - pad - (Math.max(0, Math.min(maxValue, Number(point[field] || 0))) / maxValue) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const latest = ordered[ordered.length - 1] || {};
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${field} trend chart">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="chart-axis"></line>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="chart-axis"></line>
      <polyline points="${coords.join(" ")}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
      ${coords.map((coord) => {
        const [x, y] = coord.split(",");
        return `<circle cx="${x}" cy="${y}" r="4" fill="${color}"></circle>`;
      }).join("")}
      <text x="${pad}" y="17" class="chart-label">Latest: ${formatDecimal(latest[field], 2)}</text>
    </svg>
  `;
}

function renderCharts(trends = []) {
  byId("success-chart").innerHTML = lineChart(trends, "success_rate", "#167a5b");
  byId("failure-chart").innerHTML = lineChart(trends, "failure_rate", "#b42318");
  byId("reliability-chart").innerHTML = lineChart(trends, "reliability_score", "#2457c5");
}

function renderHistory(runs = []) {
  const table = byId("benchmark-history-table");
  if (!table) {
    return;
  }
  if (!runs.length) {
    table.innerHTML = `<tr><td colspan="7">No benchmark runs yet. Generate sample data to populate the dashboard.</td></tr>`;
    return;
  }
  table.innerHTML = runs.map((run) => `
    <tr>
      <td><span class="model-name">${escapeHtml(run.run_id)}</span></td>
      <td>${escapeHtml(run.model)}</td>
      <td>${formatNumber(run.total_workflows)}</td>
      <td>${formatPercent(run.success_rate)}</td>
      <td>${formatPercent(run.failure_rate)}</td>
      <td>${formatDecimal(run.reliability_score_v2, 2)}</td>
      <td>${formatDate(run.created_at)}</td>
    </tr>
  `).join("");
}

async function loadRunner() {
  const payload = await jsonRequest("/api/benchmark-runner/history");
  renderOverview(payload.overview || {});
  renderCharts(payload.trends || []);
  renderHistory(payload.runs || []);
  setBusy("Benchmark data loaded");
}

function formPayload() {
  const targetValue = byId("runner-target").value;
  const seedValue = byId("runner-seed").value;
  return {
    model: byId("runner-model").value.trim() || "software-simulated-agent",
    provider_url: byId("runner-provider").value.trim() || "local-simulator",
    workflow_count: Number(byId("runner-count").value || 50),
    scenario: byId("runner-scenario").value,
    target_success_rate: targetValue === "" ? null : Number(targetValue),
    seed: seedValue === "" ? null : Number(seedValue),
  };
}

function wireRunner() {
  const form = byId("benchmark-form");
  const sampleButton = byId("sample-data-button");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        setBusy("Running benchmark...");
        await jsonRequest("/api/benchmark-runner/run", {
          method: "POST",
          body: JSON.stringify(formPayload()),
        });
        window.softwareTrack?.("benchmark_run");
        await loadRunner();
        setBusy("Benchmark run completed");
      } catch (error) {
        setBusy(`Benchmark error: ${error.message}`);
      }
    });
  }
  if (sampleButton) {
    sampleButton.addEventListener("click", async () => {
      try {
        sampleButton.disabled = true;
        setBusy("Generating sample benchmark data...");
        await jsonRequest("/api/benchmark-runner/sample-data", {
          method: "POST",
          body: JSON.stringify({
            runs: 6,
            workflow_count: Number(byId("runner-count").value || 40),
            seed: byId("runner-seed").value === "" ? null : Number(byId("runner-seed").value),
          }),
        });
        window.softwareTrack?.("benchmark_run");
        await loadRunner();
        setBusy("Sample data generated");
      } catch (error) {
        setBusy(`Sample data error: ${error.message}`);
      } finally {
        sampleButton.disabled = false;
      }
    });
  }
}

wireRunner();
loadRunner().catch((error) => setBusy(`Benchmark runner error: ${error.message}`));
